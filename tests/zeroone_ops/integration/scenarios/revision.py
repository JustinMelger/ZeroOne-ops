"""Shared revision fixtures using real provider persistence and local Git."""

import httpx

from zeroone_ops.models.analysis import (
    BatchIssueAnalysis,
    IssueContext,
    SemanticSafetyAssessment,
    StructuredEditProposal,
    TextEdit,
)
from zeroone_ops.models.batch_execution import BatchAnalysisCoverage
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.providers.review.gitlab import GitLabReviewClient
from zeroone_ops.services.remediation.recovery.publication_retry_service import (
    PublicationRetryService,
)
from zeroone_ops.services.shared.branch_revision_lookup import (
    GitHubBranchRevisionLookup,
    GitLabBranchRevisionLookup,
)

from .harness import SCOPE, ScenarioHarness
from .repository import TARGET_PATH, ScenarioRepository, git


def persist_work_item(harness: ScenarioHarness, state: WorkItemState) -> WorkItemState:
    """Seed route evidence through real provider rendering and persistence."""
    options = {"repository_id" if harness.api.platform == "github" else "project_id": SCOPE}
    return harness.work_items.upsert_work_item(work_item=state, **options).work_item


def configure_request_lookup(harness: ScenarioHarness, http: httpx.Client) -> None:
    """Route native revision lookup and recorded retry exclusively through fake HTTP."""
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
        """Require a persisted revision claim and verified checkout before analysis."""
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
