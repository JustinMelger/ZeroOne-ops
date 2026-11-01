"""Provider-neutral remediation orchestration over shared execution services."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from zeroone_ops.models.analysis import ValidationOutcome
from zeroone_ops.models.batch_execution import BatchAnalysisRejection
from zeroone_ops.models.change_request import ChangeRequestInfo, ChangeRequestState
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.remediation import RemediationCompletionResult, RemediationExecutionTarget
from zeroone_ops.models.state import FailureDetails, FailureStage, RunRecord, RunStatus, utc_now
from zeroone_ops.models.work_item import (
    PublicationRetryState,
    WorkItemExecutionFailure,
    WorkItemSemanticSafety,
    WorkItemState,
)
from zeroone_ops.services.remediation.batch_execution_scope_service import (
    BatchExecutionScopeService,
)
from zeroone_ops.services.remediation.change_request_publisher import (
    build_remediation_change_request_publisher,
)
from zeroone_ops.services.remediation.control_plane import (
    RemediationControlPlane,
    build_remediation_control_plane,
)
from zeroone_ops.services.remediation.execution_service import ExecutionResult, ExecutionService
from zeroone_ops.services.remediation.recovery.publication_retry_service import (
    PublicationRetryService,
)
from zeroone_ops.services.remediation.recovery.recorded_publication_retry_coordinator import (
    RecordedPublicationRetryCoordinator,
)
from zeroone_ops.services.remediation.remediation_context_builder import (
    RemediationContextBuilder,
)
from zeroone_ops.services.remediation.revision_target_preparation_service import (
    RevisionTargetPreparationService,
)
from zeroone_ops.services.remediation.validation_feedback.failure_evidence import (
    sanitize_validation_text,
)
from zeroone_ops.services.shared.branch_revision_lookup import build_branch_revision_lookup
from zeroone_ops.services.shared.projection_payload import ProjectionSizeExceeded
from zeroone_ops.services.shared.run_state_service import RunStateService, RunSummary

LOGGER = logging.getLogger(__name__)
_FAILURE_OUTPUT_LIMIT = 2_000
_VALIDATION_SETUP_GUIDANCE = (
    "Check the workflow logs for package-registry access, missing validation tools, "
    "lockfile compatibility, or repository-specific authentication requirements."
)


class _WorkItemIntakeResult(Protocol):
    """Expose one provider-local claimed work item to shared execution."""

    @property
    def selected_target(self) -> RemediationExecutionTarget | None:
        """Return the execution target selected from authoritative state."""

    @property
    def claimed_work_item(self) -> WorkItemState | None:
        """Return the selected work item after an optional persistent claim."""

    @property
    def item_count(self) -> int:
        """Return the number of authoritative work items considered."""

    @property
    def message(self) -> str:
        """Return the provider-local no-selection diagnostic."""


class WorkItemRemediationRunner:
    """Execute one claimed provider work item through the shared remediation core."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        run_state_service: RunStateService,
        execution_service: ExecutionService | None = None,
        remediation_control_plane: RemediationControlPlane | None = None,
        publication_retry_service: PublicationRetryService | None = None,
        execution_url_builder: Callable[[], str | None] | None = None,
        change_request_state_lookup: Callable[[int], ChangeRequestState] | None = None,
        batch_policy: PolicyState | None = None,
    ) -> None:
        """Initialize shared remediation execution over one work-item control plane."""
        self.repo_root = repo_root
        self.config = config
        self.run_state_service = run_state_service
        self.execution_service = execution_service or ExecutionService(
            repo_root=repo_root,
            config=config,
        )
        self.remediation_control_plane = (
            remediation_control_plane or build_remediation_control_plane(config)
        )
        self.publication_retry_service = publication_retry_service
        self.execution_url_builder = execution_url_builder or (lambda: None)
        self.change_request_state_lookup = change_request_state_lookup
        self.batch_policy = batch_policy

    def run(self, *, record: RunRecord, active_dry_run: bool) -> RunSummary:
        """Select, execute, and project one provider work item."""
        if not active_dry_run and self.config.execution_mode != "ci":
            message = (
                "Work-item remediation live execution is only supported in CI mode. "
                "Use --dry-run locally."
            )
            return self.run_state_service.fail_run(
                record=record,
                error_message=message,
                failure=FailureDetails(stage=FailureStage.ISSUE_INTAKE, message=message),
            )

        try:
            intake_result = self._select_and_claim(
                persist=not active_dry_run,
                run_id=record.run_id,
            )
        except ProjectionSizeExceeded as error:
            message = f"Batch claim withheld: {error}"
            return self.run_state_service.fail_run(
                record=record,
                error_message=message,
                failure=FailureDetails(stage=FailureStage.CONTROL_PLANE_UPDATE, message=message),
            )
        selected_target = intake_result.selected_target
        claimed_work_item = intake_result.claimed_work_item
        if selected_target is None or claimed_work_item is None:
            return self.run_state_service.finish_no_issue(
                record=record,
                message=intake_result.message,
                issue_count=intake_result.item_count,
            )

        revision_target, revision_failure = RevisionTargetPreparationService(
            change_request_state_lookup=self.change_request_state_lookup,
        ).prepare(
            selected_target=selected_target,
            claimed_work_item=claimed_work_item,
        )
        if revision_failure is not None:
            self._mark_blocked_best_effort(
                selected_target=selected_target,
                claimed_work_item=claimed_work_item,
                active_dry_run=active_dry_run,
                failure=revision_failure,
                run_id=record.run_id,
            )
            return self.run_state_service.finish_work_item(
                record=record,
                work_item_id=selected_target.item_id,
                status=RunStatus.FAILED,
                message=revision_failure.message,
                failure=revision_failure,
            )
        selected_target = revision_target

        if claimed_work_item.publication_retry is not None:
            return RecordedPublicationRetryCoordinator(
                config=self.config,
                run_state_service=self.run_state_service,
                remediation_control_plane=self.remediation_control_plane,
                retry_service_factory=self._build_publication_retry_service,
                logger=LOGGER,
            ).run(
                selected_target=selected_target,
                claimed_work_item=claimed_work_item,
                record=record,
                active_dry_run=active_dry_run,
            )

        if selected_target.revision_branch is not None:
            execution_result = self.execution_service.execute_revision(
                selected_issue=selected_target, dry_run=active_dry_run
            )
        else:
            if selected_target.batch is not None:
                stopped = self._finish_nonexecuting_batch(
                    record=record,
                    selected_target=selected_target,
                    claimed_work_item=claimed_work_item,
                    active_dry_run=active_dry_run,
                )
                if stopped is not None:
                    return stopped
            try:
                context = RemediationContextBuilder(self.repo_root, self.config).build(
                    selected_target
                )
            except (OSError, UnicodeError):
                if selected_target.batch is None:
                    raise
                context = None
            if context is None:
                message = (
                    f"Context unavailable for remediation work item {selected_target.item_id}."
                )
                failure = FailureDetails(stage=FailureStage.ISSUE_INTAKE, message=message)
                self._mark_blocked_best_effort(
                    selected_target=selected_target,
                    claimed_work_item=claimed_work_item,
                    active_dry_run=active_dry_run,
                    failure=failure,
                    run_id=record.run_id,
                )
                return self.run_state_service.finish_work_item(
                    record=record,
                    work_item_id=selected_target.item_id,
                    status=RunStatus.FAILED,
                    message=message,
                    failure=failure,
                )
            execution_result = self.execution_service.execute_with_context(
                selected_issue=selected_target,
                context=context,
                dry_run=active_dry_run,
                attempt_number=claimed_work_item.attempt_number,
            )
        if execution_result.analysis_result.batch_attempt is not None:
            selected_target = selected_target.model_copy(
                update={"batch_attempt": execution_result.analysis_result.batch_attempt}
            )
        validation_outcome = _validation_outcome(execution_result)
        if execution_result.failure is not None:
            self._mark_blocked_best_effort(
                publication_retry=execution_result.publication_retry
                if selected_target.batch is not None
                else None,
                selected_target=selected_target,
                claimed_work_item=claimed_work_item,
                active_dry_run=active_dry_run,
                failure=execution_result.failure,
                run_id=record.run_id,
                semantic_safety=_semantic_safety_record(execution_result),
                batch_rejection=execution_result.analysis_result.batch_rejection,
            )
            message = _failure_summary_message(execution_result.failure)
            if execution_result.analysis_result.batch_rejection is not None:
                message += (
                    f"\nWork item: {selected_target.work_item_url or selected_target.item_id}"
                )
                if claimed_work_item.linked_change_request is not None:
                    message += (
                        "\nExisting change request: "
                        + claimed_work_item.linked_change_request.web_url
                    )
                message += (
                    "\nInspect the explanation before deciding on manual correction or a new "
                    "authorized attempt; remediation commands belong on the work-item issue."
                )
            return self.run_state_service.finish_work_item(
                record=record,
                work_item_id=selected_target.item_id,
                status=RunStatus.FAILED,
                message=message,
                branch_name=execution_result.branch_name,
                commit_sha=execution_result.commit_sha,
                failure=execution_result.failure,
            )

        if execution_result.final_status == RunStatus.REJECTED:
            if selected_target.revision_branch is not None or selected_target.batch is not None:
                self._mark_blocked_best_effort(
                    selected_target=selected_target,
                    claimed_work_item=claimed_work_item,
                    active_dry_run=active_dry_run,
                    run_id=record.run_id,
                    failure=FailureDetails(
                        stage=execution_result.terminal_rejection_stage or FailureStage.ANALYSIS,
                        message=execution_result.status_message,
                    ),
                    semantic_safety=_semantic_safety_record(execution_result),
                )
            else:
                self._mark_dismissed_best_effort(
                    selected_target=selected_target,
                    claimed_work_item=claimed_work_item,
                    active_dry_run=active_dry_run,
                    run_id=record.run_id,
                    summary=execution_result.status_message,
                    stage=execution_result.terminal_rejection_stage or FailureStage.ANALYSIS,
                    semantic_safety=(
                        None
                        if execution_result.analysis_result.semantic_safety is None
                        else WorkItemSemanticSafety(
                            assessment=execution_result.analysis_result.semantic_safety.assessment,
                            rejection_reason=execution_result.analysis_result.semantic_safety.reason,
                        )
                    ),
                )
            return self.run_state_service.finish_work_item(
                record=record,
                work_item_id=selected_target.item_id,
                status=RunStatus.REJECTED,
                message=execution_result.status_message,
                branch_name=execution_result.branch_name,
                commit_sha=execution_result.commit_sha,
                validation_outcome=validation_outcome,
            )

        if execution_result.change_request_url is not None:
            published_change_request = execution_result.published_change_request
            if published_change_request is None:
                message = (
                    "Published change request is missing identity required for work-item linkage."
                )
                failure = FailureDetails(stage=FailureStage.PUBLISH, message=message)
                self._mark_blocked_best_effort(
                    selected_target=selected_target,
                    claimed_work_item=claimed_work_item,
                    active_dry_run=active_dry_run,
                    failure=failure,
                    run_id=record.run_id,
                    semantic_safety=_semantic_safety_record(execution_result),
                )
                return self.run_state_service.finish_work_item(
                    record=record,
                    work_item_id=selected_target.item_id,
                    status=RunStatus.FAILED,
                    message=message,
                    branch_name=execution_result.branch_name,
                    commit_sha=execution_result.commit_sha,
                    failure=failure,
                )
            self._sync_change_request_link_best_effort(
                selected_target=selected_target,
                claimed_work_item=claimed_work_item,
                published_change_request=published_change_request,
                active_dry_run=active_dry_run,
                semantic_safety=_semantic_safety_record(execution_result),
            )
            return self.run_state_service.finish_work_item(
                record=record,
                work_item_id=selected_target.item_id,
                status=RunStatus.CHANGE_REQUEST_CREATED,
                message=execution_result.status_message,
                branch_name=execution_result.branch_name,
                commit_sha=execution_result.commit_sha,
                change_request_url=execution_result.change_request_url,
                change_request_action=execution_result.change_request_action,
                validation_outcome=validation_outcome,
            )

        self._mark_completed_best_effort(
            selected_target=selected_target,
            claimed_work_item=claimed_work_item,
            active_dry_run=active_dry_run,
        )
        return self.run_state_service.finish_work_item(
            record=record,
            work_item_id=selected_target.item_id,
            status=RunStatus.SELECTED,
            message=execution_result.status_message,
            branch_name=execution_result.branch_name,
            commit_sha=execution_result.commit_sha,
            validation_outcome=validation_outcome,
        )

    def _finish_nonexecuting_batch(
        self,
        *,
        record: RunRecord,
        selected_target: RemediationExecutionTarget,
        claimed_work_item: WorkItemState,
        active_dry_run: bool,
    ) -> RunSummary | None:
        """Finish absence/failure before context; None authorizes the already-claimed scope."""
        decision = BatchExecutionScopeService().resolve(
            claimed_work_item, self.batch_policy, run_id=record.run_id
        )
        if decision.disposition == "all_absent":
            if active_dry_run:
                return self.run_state_service.finish_work_item(
                    record=record,
                    work_item_id=selected_target.item_id,
                    status=RunStatus.SELECTED,
                    message="Dry run: completion requires a live authoritative absence check.",
                )
            completion = self._complete_absent_batch_best_effort(
                selected_target=selected_target, claimed_work_item=claimed_work_item
            )
            return self.run_state_service.finish_work_item(
                record=record,
                work_item_id=selected_target.item_id,
                status=RunStatus.SELECTED if completion.completed else RunStatus.FAILED,
                message=completion.message,
                failure=None
                if completion.completed
                else FailureDetails(
                    stage=FailureStage.CONTROL_PLANE_UPDATE, message=completion.message
                ),
            )
        if (
            decision.disposition == "execute"
            and (
                self.batch_policy is not None
                or claimed_work_item.publication_retry is not None
                or claimed_work_item.status == "review_revision_queued"
            )
            and selected_target.batch_attempt == decision.attempt
        ):
            return None

        message = decision.reason or "Claimed batch scope no longer matches authoritative policy."
        failure = FailureDetails(stage=FailureStage.ISSUE_INTAKE, message=message)
        self._mark_blocked_best_effort(
            selected_target=selected_target,
            claimed_work_item=claimed_work_item,
            active_dry_run=active_dry_run,
            failure=failure,
            run_id=record.run_id,
        )
        return self.run_state_service.finish_work_item(
            record=record,
            work_item_id=selected_target.item_id,
            status=RunStatus.FAILED,
            message=message,
            failure=failure,
        )

    def _complete_absent_batch_best_effort(
        self, *, selected_target: RemediationExecutionTarget, claimed_work_item: WorkItemState
    ) -> RemediationCompletionResult:
        """Report unconfirmed completion without overwriting newer authoritative work."""
        try:
            return self.remediation_control_plane.complete_absent_batch(
                selected_issue=selected_target, existing_work_item=claimed_work_item
            )
        except Exception:
            LOGGER.warning("work-item batch absence completion failed", exc_info=True)
            return RemediationCompletionResult(False, "Batch completion could not be confirmed.")

    def _mark_blocked_best_effort(
        self,
        *,
        selected_target: RemediationExecutionTarget,
        claimed_work_item: WorkItemState,
        active_dry_run: bool,
        failure: FailureDetails | None = None,
        run_id: str | None = None,
        semantic_safety: WorkItemSemanticSafety | None = None,
        publication_retry: PublicationRetryState | None = None,
        batch_rejection: BatchAnalysisRejection | None = None,
    ) -> None:
        """Project an execution failure without replacing the primary outcome."""
        if active_dry_run:
            return
        try:
            if publication_retry is not None:
                self.remediation_control_plane.mark_execution_blocked(
                    selected_issue=selected_target,
                    existing_work_item=claimed_work_item,
                    execution_failure=self._build_execution_failure(failure=failure, run_id=run_id)
                    if failure is not None and run_id is not None
                    else None,
                    semantic_safety=semantic_safety,
                    publication_retry=publication_retry,
                )
                return
            marker = (
                self.remediation_control_plane.mark_review_feedback_required
                if claimed_work_item.status == "review_revision_queued"
                else self.remediation_control_plane.mark_execution_blocked
            )
            marker(
                selected_issue=selected_target,
                existing_work_item=claimed_work_item,
                execution_failure=(
                    None
                    if failure is None or run_id is None
                    else self._build_execution_failure(
                        failure=failure, run_id=run_id, batch_rejection=batch_rejection
                    )
                ),
                semantic_safety=semantic_safety,
            )
        except Exception:
            LOGGER.warning("work-item blocked-state projection failed", exc_info=True)

    def _sync_change_request_link_best_effort(
        self,
        *,
        selected_target: RemediationExecutionTarget,
        claimed_work_item: WorkItemState,
        published_change_request: ChangeRequestInfo,
        active_dry_run: bool,
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> None:
        """Link a published change request through the runner-owned control plane."""
        if active_dry_run:
            return
        try:
            self.remediation_control_plane.sync_change_request_link(
                selected_issue=selected_target,
                published_change_request=published_change_request,
                existing_work_item=claimed_work_item,
                semantic_safety=semantic_safety,
            )
        except Exception:
            LOGGER.warning("work-item change-request link projection failed", exc_info=True)

    def _mark_dismissed_best_effort(
        self,
        *,
        selected_target: RemediationExecutionTarget,
        claimed_work_item: WorkItemState,
        active_dry_run: bool,
        run_id: str,
        summary: str,
        stage: FailureStage,
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> None:
        """Project an intentional rejection without replacing the primary outcome."""
        if active_dry_run:
            return
        try:
            self.remediation_control_plane.mark_execution_dismissed(
                selected_issue=selected_target,
                existing_work_item=claimed_work_item,
                execution_failure=WorkItemExecutionFailure(
                    stage=stage.value,
                    summary=summary,
                    retry_count=0,
                    run_id=run_id,
                    occurred_at=utc_now(),
                    execution_url=self.execution_url_builder(),
                    status="dismissed",
                ),
                semantic_safety=semantic_safety,
            )
        except Exception:
            LOGGER.warning("work-item dismissed-state projection failed", exc_info=True)

    def _mark_completed_best_effort(
        self,
        *,
        selected_target: RemediationExecutionTarget,
        claimed_work_item: WorkItemState,
        active_dry_run: bool,
    ) -> None:
        """Project successful completion without replacing the primary outcome."""
        if active_dry_run:
            return
        try:
            self.remediation_control_plane.mark_execution_completed(
                selected_issue=selected_target,
                existing_work_item=claimed_work_item,
            )
        except Exception:
            LOGGER.warning("work-item completed-state projection failed", exc_info=True)

    def _select_and_claim(
        self,
        *,
        persist: bool,
        run_id: str,
    ) -> _WorkItemIntakeResult:
        """Return one provider-local work-item selection and claim."""
        raise NotImplementedError

    def _build_publication_retry_service(self) -> PublicationRetryService:
        """Use the injected retry service or lazily construct the existing provider boundary."""
        return self.publication_retry_service or PublicationRetryService(
            branch_revision_lookup=build_branch_revision_lookup(self.config),
            change_request_publisher=build_remediation_change_request_publisher(self.config),
        )

    def _build_execution_failure(
        self,
        *,
        failure: FailureDetails,
        run_id: str,
        batch_rejection: BatchAnalysisRejection | None = None,
    ) -> WorkItemExecutionFailure:
        """Build durable operator context for one failed remediation run."""
        summary = failure.message
        if failure.stage == FailureStage.VALIDATION_SETUP:
            summary = f"{summary} {_VALIDATION_SETUP_GUIDANCE}"
        return WorkItemExecutionFailure(
            batch_rejection=batch_rejection,
            stage=failure.stage.value,
            summary=sanitize_validation_text(summary),
            retry_count=failure.retry_count,
            run_id=run_id,
            occurred_at=utc_now(),
            failed_command=(
                sanitize_validation_text(failure.failed_command) if failure.failed_command else None
            ),
            exit_code=failure.exit_code,
            execution_url=self.execution_url_builder(),
            validation_outcome=failure.validation_outcome,
            validation_phase=failure.validation_phase,
            baseline_exit_code=failure.baseline_exit_code,
            diagnostic_excerpt=(
                sanitize_validation_text(failure.diagnostic_excerpt)[:2_000]
                if failure.diagnostic_excerpt
                else None
            ),
        )


def _failure_summary_message(failure: FailureDetails) -> str:
    """Return a bounded CLI diagnostic without changing persisted failure state."""
    details = [sanitize_validation_text(failure.message)]
    if failure.validation_phase:
        details.append(f"Validation phase: {failure.validation_phase}")
    if failure.failed_command:
        details.append(f"Command: {sanitize_validation_text(failure.failed_command)}")
    if failure.exit_code is not None:
        details.append(f"Exit code: {failure.exit_code}")
    if failure.baseline_exit_code is not None:
        details.append(f"Baseline exit code: {failure.baseline_exit_code}")
    output = failure.diagnostic_excerpt or failure.stderr_excerpt or failure.stdout_excerpt
    if output is None or not output.strip():
        return "\n".join(details)

    excerpt = sanitize_validation_text(output).strip()
    if len(excerpt) > _FAILURE_OUTPUT_LIMIT:
        marker = "\n... output truncated"
        excerpt = excerpt[: _FAILURE_OUTPUT_LIMIT - len(marker)] + marker
    return "\n".join(details) + f"\n\nFailed command output:\n{excerpt}"


def _validation_outcome(execution_result: ExecutionResult) -> ValidationOutcome | None:
    """Return the compact comparison outcome when feedback validation ran."""
    comparison = execution_result.analysis_result.validation_comparison
    return None if comparison is None else comparison.outcome


def _semantic_safety_record(execution_result: ExecutionResult) -> WorkItemSemanticSafety | None:
    """Return compact semantic-safety evidence for a projected execution state."""
    decision = execution_result.analysis_result.semantic_safety
    if decision is None:
        return None
    return WorkItemSemanticSafety(
        assessment=decision.assessment,
        rejection_reason=decision.reason,
    )
