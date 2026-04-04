"""Patch execution service.

This module owns patch application, validation, retry, and rollback behavior.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ai_sonar_bot.models.analysis import (
    IssueContext,
    PatchProposal,
    ValidationCommandResult,
    ValidationResult,
)
from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.models.state import FailureDetails, FailureStage
from ai_sonar_bot.providers.llm_client import LLMClientError
from ai_sonar_bot.services.edit_renderer import EditRenderError
from ai_sonar_bot.services.fix_generator import FixGenerator
from ai_sonar_bot.services.patch_applier import PatchApplier, PatchApplyError
from ai_sonar_bot.services.validator import Validator
from ai_sonar_bot.services.workspace_snapshot import WorkspaceSnapshot, WorkspaceSnapshotService


@dataclass(frozen=True)
class PatchExecutionResult:
    """Capture the outcome of applying and validating a patch."""

    summary: str
    patch: PatchProposal
    patch_applied: bool
    validation_passed: bool
    validation_result: ValidationResult | None
    workspace_snapshot: WorkspaceSnapshot | None
    failure: FailureDetails | None = None


class PatchExecutionService:
    """Apply, validate, retry, and roll back patch proposals.

    Args:
        config: Loaded application configuration.
        patch_applier: Patch applier implementation.
        validator: Validation command runner.
        workspace_snapshot_service: Workspace snapshot service.
    """

    def __init__(
        self,
        *,
        config: AppConfig,
        patch_applier: PatchApplier,
        validator: Validator,
        workspace_snapshot_service: WorkspaceSnapshotService,
    ) -> None:
        """Initialize the patch execution service."""
        self.config = config
        self.patch_applier = patch_applier
        self.validator = validator
        self.workspace_snapshot_service = workspace_snapshot_service

    def execute(
        self,
        *,
        dry_run: bool,
        patch: PatchProposal,
        summary: str,
        fix_generator: FixGenerator,
        selected_issue: SonarIssue,
        context: IssueContext,
        patch_factory: Callable[..., PatchProposal],
    ) -> PatchExecutionResult:
        """Apply a patch locally and run configured validation commands."""
        for attempt in range(self.config.max_retry_count + 1):
            snapshot = self.workspace_snapshot_service.capture(patch.files_touched)
            try:
                self.patch_applier.validate(patch)
                self.patch_applier.apply(patch)
            except PatchApplyError as error:
                self.workspace_snapshot_service.restore(snapshot)
                return PatchExecutionResult(
                    summary=f"{summary}. Patch apply failed: {error}",
                    patch=patch,
                    patch_applied=False,
                    validation_passed=False,
                    validation_result=None,
                    workspace_snapshot=snapshot,
                    failure=FailureDetails(
                        stage=FailureStage.PATCH_APPLY,
                        message=f"Patch apply failed: {error}",
                        retry_count=attempt,
                        stdout_excerpt=_truncate_output(patch.unified_diff),
                    ),
                )

            validation_result = self.validator.run(self.config.validation_commands)
            if validation_result.passed:
                mode_label = "dry-run" if dry_run else "run"
                success_summary = (
                    f"{summary}. Patch applied locally in {mode_label}. "
                    f"{validation_result.summary}"
                )
                if attempt > 0:
                    success_summary = (
                        f"{summary}. Patch applied locally in {mode_label}. "
                        f"{validation_result.summary} after retry {attempt}."
                    )
                return PatchExecutionResult(
                    summary=success_summary,
                    patch=patch,
                    patch_applied=True,
                    validation_passed=True,
                    validation_result=validation_result,
                    workspace_snapshot=snapshot,
                )

            self.workspace_snapshot_service.restore(snapshot)
            if attempt >= self.config.max_retry_count:
                mode_label = "dry-run" if dry_run else "run"
                return PatchExecutionResult(
                    summary=(
                        f"{summary}. Patch applied locally in {mode_label}. "
                        f"{validation_result.summary} Retry attempts exhausted."
                    ),
                    patch=patch,
                    patch_applied=False,
                    validation_passed=False,
                    validation_result=validation_result,
                    workspace_snapshot=snapshot,
                    failure=_build_validation_failure(
                        validation_summary=validation_result.summary,
                        retry_count=attempt,
                        command_result=validation_result.results[-1]
                        if validation_result.results
                        else None,
                    ),
                )

            try:
                patch = patch_factory(
                    fix_generator=fix_generator,
                    selected_issue=selected_issue,
                    context=context,
                )
            except (EditRenderError, LLMClientError) as error:
                return PatchExecutionResult(
                    summary=f"{summary}. Structured edit generation failed during retry: {error}",
                    patch=patch,
                    patch_applied=False,
                    validation_passed=False,
                    validation_result=validation_result,
                    workspace_snapshot=snapshot,
                    failure=FailureDetails(
                        stage=FailureStage.ANALYSIS,
                        message=f"Structured edit generation failed during retry: {error}",
                        retry_count=attempt,
                    ),
                )

        return PatchExecutionResult(
            summary=summary,
            patch=patch,
            patch_applied=False,
            validation_passed=False,
            validation_result=None,
            workspace_snapshot=None,
        )


def _build_validation_failure(
    *,
    validation_summary: str,
    retry_count: int,
    command_result: ValidationCommandResult | None,
) -> FailureDetails:
    """Build structured validation failure details."""
    stdout_excerpt = None
    stderr_excerpt = None
    failed_command = None
    exit_code = None
    if command_result is not None:
        failed_command = command_result.command
        exit_code = command_result.exit_code
        stdout_excerpt = _truncate_output(command_result.stdout)
        stderr_excerpt = _truncate_output(command_result.stderr)
    return FailureDetails(
        stage=FailureStage.VALIDATION,
        message=validation_summary,
        retry_count=retry_count,
        validation_summary=validation_summary,
        failed_command=failed_command,
        exit_code=exit_code,
        stdout_excerpt=stdout_excerpt,
        stderr_excerpt=stderr_excerpt,
    )


def _truncate_output(value: str, limit: int = 500) -> str | None:
    """Truncate command output for state persistence."""
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[:limit]}..."
