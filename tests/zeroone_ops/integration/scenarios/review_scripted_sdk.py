"""Finite SDK responses that validate real rendered review prompts before replying."""

import json
import re
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from zeroone_ops.models.review import (
    DroppedCandidate,
    OverlapReconciliationResult,
    PrecisionAcceptedFinding,
    PrecisionReviewDecision,
    ReviewResult,
)
from zeroone_ops.models.work_item import WorkItemState

from .review_cases import REVIEW_PATH, ReviewCase


def untrusted_block(prompt: str, label: str) -> str:
    """Extract one evidence block rather than snapshotting complete prompt prose."""
    begin, end = f"<<BEGIN UNTRUSTED {label}>>", f"<<END UNTRUSTED {label}>>"
    assert prompt.count(begin) == prompt.count(end) == 1, f"Missing or repeated {label}"
    return prompt.split(begin, 1)[1].split(end, 1)[0].strip()


@dataclass(frozen=True)
class ReviewSDKCall:
    """Capture schema, prompt, and typed response without claiming SDK JSON parsing."""

    schema: type[BaseModel]
    prompt: str
    output: BaseModel


@dataclass
class ScriptedReviewSDK:
    """Require candidate then precision calls for each explicitly supplied case."""

    case: ReviewCase
    linked_work_item: WorkItemState | None = None
    forbidden_markers: tuple[str, ...] = ()
    calls: list[ReviewSDKCall] = field(default_factory=list)
    candidate_ids: tuple[str, ...] = ()
    prior_case: ReviewCase | None = None
    overlap_result: OverlapReconciliationResult | None = None

    @property
    def expected_call_count(self) -> int:
        """Require the overlap stage only for an explicitly scripted repeated review."""
        return 3 if self.prior_case is not None else 2

    @property
    def responses(self) -> "ScriptedReviewSDK":
        """Expose the existing SDK response interface to the real LLM adapter."""
        return self

    def parse(
        self,
        *,
        model: str,
        input: list[dict[str, str]],
        text_format: type[BaseModel],
        reasoning: dict[str, str],
    ) -> SimpleNamespace:
        """Use a pytest failure so the adapter cannot swallow a broken test contract."""
        try:
            index = len(self.calls)
            assert index < self.expected_call_count, "Unexpected additional review model request"
            assert model == "offline-review-model"
            assert (
                text_format
                is (
                    ReviewResult,
                    PrecisionReviewDecision,
                    OverlapReconciliationResult,
                )[index]
            )
            assert reasoning == {"effort": "high" if index == 1 else "medium"}
            assert len(input) == 2 and [message["role"] for message in input] == ["system", "user"]
            prompt = input[1]["content"]
            if index == 2:
                assert "Do not invent new findings" in input[0]["content"]
                output = self._overlap_response(prompt)
                self.calls.append(ReviewSDKCall(text_format, prompt, output.model_copy(deep=True)))
                return SimpleNamespace(output_parsed=output)
            assert "untrusted" in input[0]["content"].lower()
            self._assert_prompt(prompt)
            if index == 0:
                output = ReviewResult(
                    classification="findings_present",
                    summary="One candidate requires precision.",
                    findings=[self.case.finding.model_copy(deep=True)],
                )
            else:
                output = self._precision_response(prompt)
            self.calls.append(ReviewSDKCall(text_format, prompt, output.model_copy(deep=True)))
            return SimpleNamespace(output_parsed=output)
        except AssertionError as error:
            pytest.fail(str(error), pytrace=False)

    def _assert_prompt(self, prompt: str) -> None:
        """Bind supplied source, guidance, identity, and verified evidence to this fixture."""
        for expected in (
            f"Change request number: {self.case.number}",
            f"Title: Review {self.case.marker}",
            f"Source branch: {self.case.branch}",
            "Target branch: main",
            f"Head SHA: {self.case.head_sha}",
        ):
            assert expected in prompt, f"Missing review identity: {expected}"
        assert not any(marker in prompt for marker in self.forbidden_markers), (
            "Cross-request model context"
        )
        assert f"Check {self.case.marker} against the changed code." in prompt, (
            "Missing repository guidance"
        )
        changed = untrusted_block(prompt, f"Changed file: {REVIEW_PATH}")
        assert f"Diff:\n{self.case.diff}" in changed, "Missing request-specific diff"
        match = re.search(r"Context lines (\d+)-(\d+):\n(.*)", changed, flags=re.DOTALL)
        assert match is not None, "Missing source context"
        expected_lines = self.case.after.splitlines()
        assert (int(match[1]), int(match[2])) == (1, len(expected_lines)), (
            "Incomplete source context"
        )
        supplied = match[3].splitlines()
        assert len(supplied) == len(expected_lines), "Incomplete source context"
        for number, (actual, expected) in enumerate(zip(supplied, expected_lines, strict=True), 1):
            prefix, separator, source = actual.partition(": ")
            assert separator and prefix.strip() == str(number)
            assert source == expected, "Incorrect request source context"
        if self.linked_work_item is not None:
            packet = json.loads(untrusted_block(prompt, "Verified linked batch attempt evidence"))
            attempt = self.linked_work_item.batch_attempt
            assert packet["batch_id"] == attempt.batch_id
            assert packet["attempt_number"] == attempt.attempt_number
            assert packet["targeted_members"] == [
                {
                    "finding_id": member.finding_id,
                    "path": member.repository_path,
                    "rule": member.remediation_context.diagnostic_code,
                    "line_start": member.line_start,
                    "line_end": member.line_end,
                    "message": member.summary,
                }
                for member in attempt.members
            ], "Missing linked member evidence"
            assert packet["omitted_member_count"] == 0 and packet["coverage_complete"]
            rationale = self.linked_work_item.semantic_safety.assessment
            evidence = untrusted_block(prompt, "Remediation-authored context")
            assert (
                rationale.current_behavior in evidence and rationale.intended_behavior in evidence
            )
            assert all(claim in evidence for claim in rationale.preservation_evidence)
        else:
            assert "Verified linked batch attempt evidence" not in prompt

    def _precision_response(self, prompt: str) -> PrecisionReviewDecision:
        """Require forwarded evidence and the explicitly expected latest prior review."""
        if self.prior_case is None:
            assert "Latest prior review context:\n(none)" in prompt, (
                "Unexpected prior request context"
            )
        else:
            prior = untrusted_block(prompt, "Latest prior review pass")
            assert f"reviewed_head_sha={self.prior_case.head_sha}" in prior
            assert self.prior_case.finding.title in prior
            assert self.prior_case.number == self.case.number
        candidates = untrusted_block(prompt, "Candidate findings")
        identifiers = tuple(re.findall(r"^- candidate_id=(.+)$", candidates, flags=re.MULTILINE))
        assert len(identifiers) == 1, "Missing or duplicate forwarded candidate"
        finding = self.case.finding
        for expected in (
            f"severity={finding.severity}",
            f"path={finding.file_path}",
            f"lines={finding.line_start}-{finding.line_end}",
            f"title={finding.title}",
            f"evidence={finding.evidence}",
            f"explanation={finding.explanation}",
            f"suggested_follow_up={finding.suggested_follow_up}",
        ):
            assert expected in candidates, "Missing or incorrect forwarded candidate evidence"
        self.candidate_ids = identifiers
        for field_name in ("symbol", "issue_kind", "region_hint"):
            value = getattr(finding, field_name)
            if value is not None:
                assert f"{field_name}={value}" in candidates
        if self.linked_work_item is not None:
            assert untrusted_block(prompt, "Verified linked batch attempt evidence") == (
                untrusted_block(self.calls[0].prompt, "Verified linked batch attempt evidence")
            )
        if self.case.name == "mr24":
            return PrecisionReviewDecision(
                review_classification="no_findings",
                decision_summary="No introduced defect.",
                decision_rationale="The reported runtime behavior predates the annotation change.",
                dropped_candidates=[
                    DroppedCandidate(
                        candidate_id=identifiers[0],
                        drop_reason="unsupported_scope",
                        notes="Pre-existing behavior is not an introduced defect.",
                    )
                ],
            )
        return PrecisionReviewDecision(
            review_classification="findings_present",
            decision_summary="One introduced defect.",
            decision_rationale=finding.explanation,
            confidence_level=0.95,
            accepted_findings=[
                PrecisionAcceptedFinding(
                    source_candidate_ids=list(identifiers),
                    severity=finding.severity,
                    file_path=finding.file_path,
                    line_start=finding.line_start,
                    line_end=finding.line_end,
                    symbol=finding.symbol,
                    issue_kind=finding.issue_kind,
                    region_hint=finding.region_hint,
                    title=finding.title,
                    summary=finding.title,
                    evidence=[finding.evidence],
                    why_it_matters=finding.explanation,
                    recommended_follow_up=finding.suggested_follow_up,
                )
            ],
        )

    def _overlap_response(self, prompt: str) -> OverlapReconciliationResult:
        """Check the real bounded current/prior packet before returning scripted continuity."""
        assert self.prior_case is not None and self.overlap_result is not None
        assert f"Change request number: {self.case.number}" in prompt
        assert f"Current reviewed SHA: {self.case.head_sha}" in prompt
        assert f"Prior reviewed SHA: {self.prior_case.head_sha}" in prompt
        assert self.overlap_result.prior_reviewed_head_sha == self.prior_case.head_sha
        current = untrusted_block(prompt, "Current findings")
        prior = untrusted_block(prompt, "Prior findings")
        assert f"current[0] {REVIEW_PATH}: {self.case.finding.title}" in current
        assert f"prior[0] {REVIEW_PATH}: {self.prior_case.finding.title}" in prior
        candidates = untrusted_block(prompt, "Overlap candidates")
        if any(item.outcome == "still_unresolved" for item in self.overlap_result.resolutions):
            assert "current[0] <-> prior[0]" in candidates
        else:
            assert candidates == "- (none)"
        return self.overlap_result.model_copy(deep=True)
