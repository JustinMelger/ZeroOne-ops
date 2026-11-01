"""Characterize recorded publication and same-request revision using real Git."""

from datetime import UTC, datetime

import httpx
import pytest

from zeroone_ops.models.analysis import (
    BatchIssueAnalysis,
    IssueContext,
    SemanticSafetyAssessment,
    StructuredEditProposal,
    TextEdit,
)
from zeroone_ops.models.batch_execution import BatchAnalysisCoverage
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.work_item import (
    ProjectedReviewFeedback,
    ProjectedReviewFinding,
    ProjectedReviewState,
    ReviewRevisionRequest,
    WorkItemState,
)
from zeroone_ops.providers.review.gitlab import GitLabReviewClient
from zeroone_ops.services.remediation.recovery.publication_retry_service import (
    PublicationRetryService,
)
from zeroone_ops.services.shared.branch_revision_lookup import (
    GitHubBranchRevisionLookup,
    GitLabBranchRevisionLookup,
)

from .harness import RUN_ID, SCOPE, ScenarioHarness, compose_scenario
from .provider_api import ScenarioProviderAPI
from .repository import TARGET_PATH, ScenarioRepository, create_repository, git


def _persist(harness: ScenarioHarness, state: WorkItemState) -> WorkItemState:
    """Seed authorized route state through real provider rendering and persistence."""
    options = {"repository_id" if harness.api.platform == "github" else "project_id": SCOPE}
    return harness.work_items.upsert_work_item(work_item=state, **options).work_item


def _lookup(harness: ScenarioHarness, http: httpx.Client) -> None:
    """Keep native lookup and retry services real while routing their HTTP offline."""
    publisher = harness.engine.publish_service.change_request_publisher
    if harness.api.platform == "github":
        client = publisher.github_client
        harness.runner.change_request_state_lookup = lambda number: client.get_change_request_state(
            repository_id=SCOPE,
            change_request_number=number,
        )
        branch_lookup = GitHubBranchRevisionLookup(client)
    else:
        client = publisher.gitlab_client
        review_client = GitLabReviewClient(client.config, http_client=http)
        harness.runner.change_request_state_lookup = lambda number: (
            review_client.get_change_request_state(
                project_id=SCOPE,
                change_request_number=number,
            )
        )
        branch_lookup = GitLabBranchRevisionLookup(client)
    harness.runner.publication_retry_service = PublicationRetryService(
        branch_revision_lookup=branch_lookup,
        change_request_publisher=publisher,
    )


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("uncertain_create", [False, True])
def test_recorded_retry_publishes_existing_commit_without_execution(
    tmp_path, monkeypatch, platform, uncertain_create
):
    repository = create_repository(tmp_path)
    api = ScenarioProviderAPI(platform, allow_request_reuse=uncertain_create)
    fail_create = True

    def respond(request):
        if (
            fail_create
            and request.method == "POST"
            and request.url.path.endswith(("/pulls", "/merge_requests"))
        ):
            if uncertain_create:
                api.respond(request)
            return httpx.Response(503, json={"message": "Temporary publication outage"})
        return api.respond(request)

    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(respond)
    ) as http:
        harness = compose_scenario(repository, api, http, (None,), monkeypatch)
        harness.sync("promotion")
        original = harness.work_item()
        failed = harness.runner.run(record=harness.runs.start_run(RUN_ID), active_dry_run=False)
        blocked = harness.work_item()
        assert failed.status.value == "failed" and blocked.status == "blocked"
        retry = blocked.publication_retry
        assert retry is not None
        assert len(api.requests) == int(uncertain_create)
        assert blocked.claim is None
        assert (
            git(repository.remote, "rev-parse", f"refs/heads/{retry.branch_name}")
            == retry.commit_sha
        )
        api.branch_head_lookup = lambda branch: git(
            repository.remote, "rev-parse", f"refs/heads/{branch}"
        )
        _lookup(harness, http)
        blocked = blocked.model_copy(
            update={
                "batch": blocked.batch.model_copy(
                    update={
                        "observations": tuple(
                            observation.model_copy(update={"last_confirmed_presence": "absent"})
                            for observation in blocked.batch.observations
                        )
                    }
                )
            }
        )
        _persist(harness, blocked.model_copy(update={"status": "approved"}))
        before = git(repository.root, "rev-parse", "HEAD")
        model_counts = (len(harness.model.analysis_contexts), len(harness.model.edit_contexts))
        validations = []
        original_validation = harness.engine.analysis_service.validator.run_all

        def validation(commands):
            validations.append(commands)
            return original_validation(commands)

        monkeypatch.setattr(harness.engine.analysis_service.validator, "run_all", validation)
        monkeypatch.setattr(
            harness.engine.branch_manager,
            "push_current_branch",
            lambda: pytest.fail("Recorded retry must not push"),
        )
        monkeypatch.setattr(
            harness.runner,
            "load_batch_policy",
            lambda: pytest.fail("Recorded retry must not load fresh policy"),
        )
        if not uncertain_create:
            repeat = harness.runner.run(
                record=harness.runs.start_run("retry-failed"), active_dry_run=False
            )
            assert repeat.status.value == "failed"
            assert harness.work_item().publication_retry == retry
            assert harness.work_item().claim is None
            _persist(harness, harness.work_item().model_copy(update={"status": "approved"}))
        fail_create = False
        summary = harness.runner.run(
            record=harness.runs.start_run("retry-success"), active_dry_run=False
        )
        final = harness.work_item()
        assert summary.status.value == "change_request_created", summary.message
        action = "reused" if uncertain_create else "created"
        assert f"Change request {action}:" in summary.message
        assert final.status == "in_progress" and final.claim is None
        assert final.publication_retry is None and final.linked_change_request is not None
        assert final.batch.members == original.batch.members
        assert final.batch_attempt == retry.batch_attempt
        assert final.semantic_safety.assessment == retry.semantic_safety
        assert len(api.requests) == 1
        assert model_counts == (
            len(harness.model.analysis_contexts),
            len(harness.model.edit_contexts),
        )
        assert not validations
        assert git(repository.root, "rev-parse", "HEAD") == before == retry.commit_sha
        assert (
            git(
                repository.remote,
                "rev-list",
                "--count",
                f"{repository.original_sha}..{retry.commit_sha}",
            )
            == "1"
        )
        assert (
            git(repository.remote, "diff", "--name-only", repository.original_sha, retry.commit_sha)
            == TARGET_PATH
        )


class RevisionModel:
    """Supply one analysis and a bounded edit script against the checked-out revision."""

    def __init__(
        self,
        harness: ScenarioHarness,
        repository: ScenarioRepository,
        original: WorkItemState,
        sha: str,
        succeeds: bool,
    ) -> None:
        """Retain expected revision evidence and one finite edit script."""
        self.harness, self.repository, self.original, self.sha = harness, repository, original, sha
        self.succeeds = succeeds
        self.analysis_count = self.edit_count = 0
        self.source = repository.source.read_text()

    def analyze_issue(
        self,
        issue: RemediationExecutionTarget,
        context: IssueContext,
    ) -> BatchIssueAnalysis:
        """Require a persisted revision claim and the verified checkout before analysis."""
        assert self.analysis_count == 0
        self.analysis_count += 1
        assert git(self.repository.root, "rev-parse", "HEAD") == self.sha
        assert self.repository.source.read_text() == self.source
        assert "import os" not in context.snippet.content
        assert context.prior_review_feedback.findings[0].evidence == "Keep the exported value"
        assert context.batch_attempt.members == self.original.batch_attempt.members
        current = self.harness.work_item()
        assert current.status == "review_revision_queued" and current.claim is not None
        return BatchIssueAnalysis(
            issue_key=issue.source_ref,
            classification="auto_fixable",
            summary="Annotate value",
            proposed_strategy="Preserve the value",
            batch_coverage=BatchAnalysisCoverage(
                addressable_ids=tuple(member.finding_id for member in issue.batch_attempt.members)
            ),
            semantic_safety=SemanticSafetyAssessment(
                current_behavior="Export value 1",
                intended_behavior="Annotate the same value",
                preservation_evidence=["Value remains 1"],
            ),
        )

    def generate_structured_edit(
        self,
        issue: RemediationExecutionTarget,
        context: IssueContext,
    ) -> StructuredEditProposal:
        """Generate only the scripted one-file revision from restored source evidence."""
        assert self.edit_count < (1 if self.succeeds else 2)
        assert self.repository.source.read_text() == self.source
        assert context.batch_attempt.members == self.original.batch_attempt.members
        assert context.semantic_safety is not None
        self.edit_count += 1
        return StructuredEditProposal(
            issue_key=issue.source_ref,
            edits=[
                TextEdit(
                    file_path=TARGET_PATH,
                    search_text="value = 1",
                    replace_text="value: int = 1" if self.succeeds else "value: MissingType = 1",
                )
            ],
            commit_message="Annotate value",
            change_request_title="Annotate value",
            change_request_description="Retain the exported value",
        )


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("succeeds", [True, False])
def test_revision_uses_verified_checkout_and_original_request(
    tmp_path, monkeypatch, platform, succeeds
):
    repository = create_repository(tmp_path)
    api = ScenarioProviderAPI(platform)
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_scenario(repository, api, http, (None,), monkeypatch)
        harness.sync("promotion")
        first = harness.runner.run(record=harness.runs.start_run(RUN_ID), active_dry_run=False)
        assert first.status.value == "change_request_created"
        original = harness.work_item()
        branch = git(repository.root, "branch", "--show-current")
        sha = git(repository.root, "rev-parse", "HEAD")
        source = repository.source.read_text()
        api.branch_head_lookup = lambda branch: git(
            repository.remote, "rev-parse", f"refs/heads/{branch}"
        )
        _lookup(harness, http)
        feedback = ProjectedReviewFeedback(
            summary="Preserve value",
            finding_count=1,
            findings=[
                ProjectedReviewFinding(
                    title="Keep constant",
                    file_path=TARGET_PATH,
                    evidence="Keep the exported value",
                    explanation="Callers import value",
                    suggested_follow_up="Annotate without changing it",
                )
            ],
        )
        queued = original.model_copy(
            update={
                "status": "review_revision_queued",
                "projected_review": ProjectedReviewState(
                    classification="findings_present",
                    reviewed_sha=sha,
                    follow_up_required=True,
                    feedback=feedback,
                ),
                "review_revision_request": ReviewRevisionRequest(
                    actor="operator",
                    request_reference="note:1",
                    occurred_at=datetime.now(UTC),
                    reviewed_sha=sha,
                ),
            }
        )
        _persist(harness, queued)
        model = RevisionModel(harness, repository, original, sha, succeeds)
        monkeypatch.setattr(harness.engine.analysis_service, "_build_llm_client", lambda: model)
        git(repository.root, "checkout", "main")
        writes_before = len(api.calls)

        summary = harness.runner.run(
            record=harness.runs.start_run("revision"), active_dry_run=False
        )

        final = harness.work_item()
        assert final.status == ("in_progress" if succeeds else "review_feedback_required"), (
            summary.message
        )
        assert final.claim is None and final.review_revision_request is None
        assert final.last_revision_command.request_reference == "note:1"
        assert final.linked_change_request == original.linked_change_request
        assert final.projected_review.feedback == feedback
        assert final.batch.members == original.batch.members
        assert final.batch_attempt.members == original.batch_attempt.members
        assert len(api.requests) == 1
        assert not any(
            path.endswith(("/pulls", "/merge_requests")) for _, path in api.calls[writes_before:]
        )
        assert model.analysis_count == 1 and model.edit_count == (1 if succeeds else 2)
        remote_sha = git(repository.remote, "rev-parse", f"refs/heads/{branch}")
        if succeeds:
            assert summary.status.value == "change_request_created"
            assert remote_sha != sha
            assert git(repository.remote, "rev-parse", f"{remote_sha}^") == sha
            assert git(repository.remote, "diff", "--name-only", sha, remote_sha) == TARGET_PATH
        else:
            assert summary.status.value == "failed"
            assert remote_sha == sha
            assert repository.source.read_text() == source
            assert git(repository.root, "rev-parse", "HEAD") == sha
            assert (
                final.execution_failure.diagnostic_excerpt
                and "NameError" in final.execution_failure.diagnostic_excerpt
            )
        assert git(repository.root, "diff", "--name-only") == ""
