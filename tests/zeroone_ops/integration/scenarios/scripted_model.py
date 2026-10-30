"""Deterministic model responses with exact request and restoration contracts."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from zeroone_ops.models.analysis import (
    BatchIssueAnalysis,
    IssueContext,
    SemanticSafetyAssessment,
    StructuredEditProposal,
    TextEdit,
)
from zeroone_ops.models.batch_execution import BatchAnalysisCoverage
from zeroone_ops.models.remediation import RemediationExecutionTarget

from .repository import ORIGINAL_SOURCE, TARGET_PATH


@dataclass
class ScriptedModel:
    """Return one analysis and a finite sequence of proposals without a model SDK."""

    source: Path
    replacements: tuple[str | None, ...]
    before_analysis: Callable[[RemediationExecutionTarget], None]
    analysis_contexts: list[IssueContext] = field(default_factory=list)
    edit_contexts: list[IssueContext] = field(default_factory=list)

    def analyze_issue(
        self, issue: RemediationExecutionTarget, context: IssueContext
    ) -> BatchIssueAnalysis:
        """Require persisted claim evidence before returning full member coverage."""
        assert not self.analysis_contexts, "Unexpected additional analysis request"
        self.before_analysis(issue)
        assert self.source.read_text(encoding="utf-8") == ORIGINAL_SOURCE
        self._assert_context_evidence(issue, context)
        self.analysis_contexts.append(context.model_copy(deep=True))
        return BatchIssueAnalysis(
            issue_key=issue.source_ref,
            classification="auto_fixable",
            summary="Remove both unused imports",
            proposed_strategy="Remove os and sys; retain the exported value.",
            batch_coverage=BatchAnalysisCoverage(
                addressable_ids=tuple(member.finding_id for member in issue.batch_attempt.members)
            ),
            semantic_safety=SemanticSafetyAssessment(
                current_behavior="Two unused imports precede the exported constant.",
                intended_behavior="Keep the constant available without the unused imports.",
                preservation_evidence=["Neither import is referenced by the constant."],
            ),
        )

    def generate_structured_edit(
        self, issue: RemediationExecutionTarget, context: IssueContext
    ) -> StructuredEditProposal:
        """Consume a finite proposal script only from restored original source."""
        index = len(self.edit_contexts)
        assert len(self.analysis_contexts) == 1
        assert index < len(self.replacements), "Unexpected additional correction request"
        assert self.source.read_text(encoding="utf-8") == ORIGINAL_SOURCE
        self._assert_context_evidence(issue, context)
        assert context.batch_coverage is not None
        assert context.batch_coverage == context.batch_attempt.coverage
        assert not context.batch_coverage.unaddressable
        assert set(context.batch_coverage.addressable_ids) == {
            member.finding_id for member in issue.batch.members
        }
        assert context.semantic_safety is not None
        if index:
            assert context.validation_feedback is not None
            assert context.validation_feedback.allowed_file_paths == [TARGET_PATH]
            failure = context.validation_feedback.failures[0]
            assert failure.baseline_exit_code == 0
            assert failure.exit_code == 2
            assert "NameError" in failure.excerpt
        else:
            assert context.validation_feedback is None
        self.edit_contexts.append(context.model_copy(deep=True))
        edits = [
            TextEdit(file_path=TARGET_PATH, search_text=f"import {name}\n", replace_text="")
            for name in ("os", "sys")
        ]
        replacement = self.replacements[index]
        if replacement is not None:
            edits.append(
                TextEdit(file_path=TARGET_PATH, search_text="value = 1", replace_text=replacement)
            )
        return StructuredEditProposal(
            issue_key=issue.source_ref,
            edits=edits,
            commit_message="Remove unused imports",
            change_request_title="Remove unused imports",
            change_request_description="Remove both imports; preserve the exported constant.",
        )

    def _assert_context_evidence(
        self, issue: RemediationExecutionTarget, context: IssueContext
    ) -> None:
        """Validate delivered evidence independently of the scripted edit's filesystem access."""
        assert context.file_path == issue.file_path == TARGET_PATH, "Wrong context file"
        assert context.full_file_included and not context.truncated
        expected_lines = ORIGINAL_SOURCE.splitlines()
        assert context.file_size_bytes == len(ORIGINAL_SOURCE.encode("utf-8"))
        assert context.snippet.start_line == 1
        assert context.snippet.end_line == len(expected_lines)
        supplied_lines = context.snippet.content.splitlines()
        assert len(supplied_lines) == len(expected_lines), "Missing source context"
        for index, (supplied, expected) in enumerate(
            zip(supplied_lines, expected_lines, strict=True), start=1
        ):
            number, separator, source_line = supplied.partition(": ")
            assert separator and number.strip() == str(index), "Invalid source line evidence"
            assert source_line == expected, "Incorrect source context"

        assert issue.batch is not None and context.batch == issue.batch, "Missing batch evidence"
        assert issue.batch_attempt is not None and context.batch_attempt is not None
        assert (
            context.batch_attempt.members == issue.batch_attempt.members == issue.batch.members
        ), "Incomplete batch member evidence"
        assert context.batch_attempt.model_copy(update={"coverage": None}) == (
            issue.batch_attempt.model_copy(update={"coverage": None})
        ), "Mismatched batch attempt evidence"
