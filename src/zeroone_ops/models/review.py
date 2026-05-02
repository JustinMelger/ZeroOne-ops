"""Review workflow models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ReviewClassification = Literal["no_findings", "findings_present", "manual_review_only"]
ReviewFindingSeverity = Literal["high", "medium", "low"]
ContinuityStatus = Literal["new", "unresolved"]
CandidateDropReason = Literal[
    "weak_evidence",
    "duplicate",
    "already_resolved",
    "unsupported_scope",
    "off_diff",
    "superseded",
]
ArtifactValidationStatus = Literal["valid", "repaired", "rejected"]


class MergeRequestChangedFile(BaseModel):
    """Represent a changed file in a merge request."""

    old_path: str
    new_path: str
    diff: str | None = None
    deleted_file: bool = False
    new_file: bool = False
    renamed_file: bool = False


class MergeRequestReviewCandidate(BaseModel):
    """Represent a merge request candidate for automated review."""

    iid: int
    title: str
    description: str | None = None
    source_branch: str
    target_branch: str
    web_url: str
    head_sha: str
    draft: bool = False
    author_username: str | None = None
    changes: list[MergeRequestChangedFile] = Field(default_factory=list)


class ReviewFileContext(BaseModel):
    """Represent one changed file plus bounded local source context."""

    file_path: str
    diff: str | None = None
    start_line: int
    end_line: int
    content: str
    full_file_included: bool
    truncated: bool
    new_file: bool = False
    deleted_file: bool = False
    renamed_file: bool = False
    helper_context: list[ReviewHelperContext] = Field(default_factory=list)


class ReviewHelperContext(BaseModel):
    """Represent one bounded supplemental helper snippet for review."""

    file_path: str
    symbol: str
    start_line: int
    end_line: int
    content: str


class RemediationReviewContext(BaseModel):
    """Represent remediation-authored MR metadata when present."""

    summary: str | None = None
    source: str | None = None
    item_reference_label: str | None = None
    item_reference: str | None = None
    rule_id: str | None = None
    severity: str | None = None
    remediation_type: str | None = None
    file_path: str | None = None
    line: int | None = None
    message: str | None = None
    validation_summary: str | None = None
    notes: str | None = None


class RepositoryGuidanceContext(BaseModel):
    """Represent one bounded repository guidance excerpt for review."""

    file_path: str
    summary: str


class PriorReviewFinding(BaseModel):
    """Represent one bounded prior-review finding summary."""

    identity: str | None = None
    legacy_identity: str | None = None
    summary: str
    severity: str | None = None
    symbol: str | None = None
    issue_kind: str | None = None
    region_hint: str | None = None


class PriorReviewPass(BaseModel):
    """Represent one bounded prior review pass on the same merge request."""

    reviewed_head_sha: str
    classification: ReviewClassification
    findings_count: int
    summary: str | None = None
    note_url: str | None = None
    findings: list[PriorReviewFinding] = Field(default_factory=list)


class PriorReviewContext(BaseModel):
    """Represent bounded prior review history for the same merge request."""

    merge_request_iid: int
    passes: list[PriorReviewPass] = Field(default_factory=list)


class MergeRequestReviewContext(BaseModel):
    """Represent deterministic review context for one merge request."""

    mr_iid: int
    title: str
    description: str | None = None
    source_branch: str
    target_branch: str
    web_url: str
    head_sha: str
    draft: bool = False
    author_username: str | None = None
    remediation_context: RemediationReviewContext | None = None
    prior_review_context: PriorReviewContext | None = None
    repository_guidance: list[RepositoryGuidanceContext] = Field(default_factory=list)
    changed_files: list[ReviewFileContext] = Field(default_factory=list)


class ReviewFinding(BaseModel):
    """Represent one structured review finding."""

    severity: ReviewFindingSeverity
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    symbol: str | None = None
    issue_kind: str | None = None
    region_hint: str | None = None
    title: str
    evidence: str
    explanation: str
    suggested_follow_up: str


class ReviewResult(BaseModel):
    """Represent the structured result of one review pass."""

    classification: ReviewClassification
    summary: str
    review_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    review_confidence_reason: str | None = None
    findings: list[ReviewFinding] = Field(default_factory=list)
    follow_up_lines: list[str] = Field(default_factory=list)


class DiffReference(BaseModel):
    """Represent one bounded diff reference carried through review stages."""

    file_path: str
    start_line: int | None = None
    end_line: int | None = None


class CandidateReviewFinding(ReviewFinding):
    """Represent one non-authoritative candidate-stage review finding."""

    candidate_id: str
    evidence_summary: str | None = None
    uncertainty_summary: str | None = None


class CandidateReviewResult(BaseModel):
    """Represent the structured output of the candidate review stage."""

    findings: list[CandidateReviewFinding] = Field(default_factory=list)


class ReconciledFinding(BaseModel):
    """Represent one accepted finding after reconciliation."""

    finding_id: str
    severity: ReviewFindingSeverity
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    symbol: str | None = None
    issue_kind: str | None = None
    region_hint: str | None = None
    title: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    diff_references: list[DiffReference] = Field(default_factory=list)
    file_paths: list[str] = Field(default_factory=list)
    why_it_matters: str
    recommended_follow_up: str | None = None
    stable_identity: str | None = None
    continuity_status: ContinuityStatus | None = None
    source_candidate_ids: list[str] = Field(default_factory=list)


class DroppedCandidate(BaseModel):
    """Represent one candidate dropped during reconciliation."""

    candidate_id: str
    drop_reason: CandidateDropReason
    notes: str | None = None


class PrecisionAcceptedFinding(BaseModel):
    """Represent one accepted finding returned by the precision stage."""

    source_candidate_ids: list[str] = Field(default_factory=list)
    severity: ReviewFindingSeverity
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    symbol: str | None = None
    issue_kind: str | None = None
    region_hint: str | None = None
    title: str
    summary: str
    evidence: list[str] = Field(default_factory=list)
    why_it_matters: str
    recommended_follow_up: str | None = None


class PrecisionReviewDecision(BaseModel):
    """Represent the candidate-bounded precision-pass output."""

    review_classification: ReviewClassification
    decision_summary: str
    decision_rationale: str
    confidence_level: float | None = Field(default=None, ge=0.0, le=1.0)
    accepted_findings: list[PrecisionAcceptedFinding] = Field(default_factory=list)
    dropped_candidates: list[DroppedCandidate] = Field(default_factory=list)


class ReconciledReviewDecision(BaseModel):
    """Represent final review meaning before artifact building."""

    review_classification: ReviewClassification
    decision_summary: str
    decision_rationale: str
    confidence_level: float | None = Field(default=None, ge=0.0, le=1.0)
    accepted_findings: list[ReconciledFinding] = Field(default_factory=list)
    dropped_candidates: list[DroppedCandidate] = Field(default_factory=list)
    prior_review_context_used: bool = False
    same_sha_review: bool = False
    repair_allowed: bool = False
    reconciled_at: datetime
    pipeline_version: str

    @classmethod
    def from_review_result(
        cls,
        review_result: ReviewResult,
        *,
        prior_review_context_used: bool,
        same_sha_review: bool,
        repair_allowed: bool,
        reconciled_at: datetime,
        pipeline_version: str,
    ) -> ReconciledReviewDecision:
        """Adapt the current review result into the staged reconciliation contract."""
        accepted_findings = [
            ReconciledFinding(
                finding_id=f"finding-{index}",
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
                diff_references=[
                    DiffReference(
                        file_path=finding.file_path,
                        start_line=finding.line_start,
                        end_line=finding.line_end,
                    )
                ],
                file_paths=[finding.file_path],
                why_it_matters=finding.explanation,
                recommended_follow_up=finding.suggested_follow_up,
            )
            for index, finding in enumerate(review_result.findings, start=1)
        ]
        return cls(
            review_classification=review_result.classification,
            decision_summary=review_result.summary,
            decision_rationale=review_result.review_confidence_reason or review_result.summary,
            confidence_level=review_result.review_confidence,
            accepted_findings=accepted_findings,
            dropped_candidates=[],
            prior_review_context_used=prior_review_context_used,
            same_sha_review=same_sha_review,
            repair_allowed=repair_allowed,
            reconciled_at=reconciled_at,
            pipeline_version=pipeline_version,
        )

    @classmethod
    def from_precision_decision(
        cls,
        precision_decision: PrecisionReviewDecision,
        *,
        prior_review_context_used: bool,
        same_sha_review: bool,
        repair_allowed: bool,
        reconciled_at: datetime,
        pipeline_version: str,
    ) -> ReconciledReviewDecision:
        """Adapt the precision-pass output into the staged reconciliation contract."""
        return cls(
            review_classification=precision_decision.review_classification,
            decision_summary=precision_decision.decision_summary,
            decision_rationale=precision_decision.decision_rationale,
            confidence_level=precision_decision.confidence_level,
            accepted_findings=[
                ReconciledFinding(
                    finding_id=f"finding-{index}",
                    severity=finding.severity,
                    file_path=finding.file_path,
                    line_start=finding.line_start,
                    line_end=finding.line_end,
                    symbol=finding.symbol,
                    issue_kind=finding.issue_kind,
                    region_hint=finding.region_hint,
                    title=finding.title,
                    summary=finding.summary,
                    evidence=list(finding.evidence),
                    diff_references=[
                        DiffReference(
                            file_path=finding.file_path,
                            start_line=finding.line_start,
                            end_line=finding.line_end,
                        )
                    ],
                    file_paths=[finding.file_path],
                    why_it_matters=finding.why_it_matters,
                    recommended_follow_up=finding.recommended_follow_up,
                    source_candidate_ids=list(finding.source_candidate_ids),
                )
                for index, finding in enumerate(
                    precision_decision.accepted_findings,
                    start=1,
                )
            ],
            dropped_candidates=list(precision_decision.dropped_candidates),
            prior_review_context_used=prior_review_context_used,
            same_sha_review=same_sha_review,
            repair_allowed=repair_allowed,
            reconciled_at=reconciled_at,
            pipeline_version=pipeline_version,
        )

    def to_review_result(self) -> ReviewResult:
        """Adapt the reconciled decision into the shared review-result shape."""
        return ReviewResult(
            classification=self.review_classification,
            summary=self.decision_summary,
            review_confidence=self.confidence_level,
            review_confidence_reason=self.decision_rationale,
            findings=[
                ReviewFinding(
                    severity=finding.severity,
                    file_path=finding.file_path,
                    line_start=finding.line_start,
                    line_end=finding.line_end,
                    symbol=finding.symbol,
                    issue_kind=finding.issue_kind,
                    region_hint=finding.region_hint,
                    title=finding.title,
                    evidence=finding.evidence[0] if finding.evidence else "",
                    explanation=finding.why_it_matters,
                    suggested_follow_up=finding.recommended_follow_up or "",
                )
                for finding in self.accepted_findings
            ],
        )


class PublishableReviewFinding(BaseModel):
    """Represent one publish-shaped review finding before markdown rendering."""

    severity: ReviewFindingSeverity
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    symbol: str | None = None
    issue_kind: str | None = None
    region_hint: str | None = None
    title: str
    evidence: str
    explanation: str
    suggested_follow_up: str
    continuity_status: ContinuityStatus | None = None


class PublishableReviewArtifact(BaseModel):
    """Represent publish-shaped review content before transport."""

    classification: ReviewClassification
    summary: str
    review_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    review_confidence_reason: str | None = None
    findings: list[PublishableReviewFinding] = Field(default_factory=list)
    follow_up_lines: list[str] = Field(default_factory=list)

    @classmethod
    def from_reconciled_decision(
        cls,
        decision: ReconciledReviewDecision,
        *,
        summary: str | None = None,
        follow_up_lines: list[str] | None = None,
    ) -> PublishableReviewArtifact:
        """Build a publish-shaped artifact without changing reconciled review meaning."""
        return cls(
            classification=decision.review_classification,
            summary=decision.decision_summary if summary is None else summary,
            review_confidence=decision.confidence_level,
            review_confidence_reason=decision.decision_rationale,
            findings=[
                PublishableReviewFinding(
                    severity=finding.severity,
                    file_path=finding.file_path,
                    line_start=finding.line_start,
                    line_end=finding.line_end,
                    symbol=finding.symbol,
                    issue_kind=finding.issue_kind,
                    region_hint=finding.region_hint,
                    title=finding.title,
                    evidence=finding.evidence[0] if finding.evidence else "",
                    explanation=finding.why_it_matters,
                    suggested_follow_up=finding.recommended_follow_up or "",
                    continuity_status=finding.continuity_status,
                )
                for finding in decision.accepted_findings
            ],
            follow_up_lines=follow_up_lines or [],
        )

    def to_review_result(self) -> ReviewResult:
        """Adapt the publish-shaped artifact back into the shared review-result shape."""
        return ReviewResult(
            classification=self.classification,
            summary=self.summary,
            review_confidence=self.review_confidence,
            review_confidence_reason=self.review_confidence_reason,
            findings=[
                ReviewFinding(
                    severity=finding.severity,
                    file_path=finding.file_path,
                    line_start=finding.line_start,
                    line_end=finding.line_end,
                    symbol=finding.symbol,
                    issue_kind=finding.issue_kind,
                    region_hint=finding.region_hint,
                    title=finding.title,
                    evidence=finding.evidence,
                    explanation=finding.explanation,
                    suggested_follow_up=finding.suggested_follow_up,
                )
                for finding in self.findings
            ],
            follow_up_lines=list(self.follow_up_lines),
        )


class ArtifactValidationIssue(BaseModel):
    """Represent one validator-detected artifact issue."""

    rule_id: str
    message: str


class ArtifactValidationResult(BaseModel):
    """Represent the validator outcome for one publish-shaped artifact."""

    status: ArtifactValidationStatus
    issues: list[ArtifactValidationIssue] = Field(default_factory=list)
    artifact: PublishableReviewArtifact | None = None


class OverlapCandidate(BaseModel):
    """Represent one app-owned overlap candidate pair for reconciliation."""

    current_finding_index: int
    prior_finding_index: int
    reasons: list[str] = Field(default_factory=list)


class OverlapPacket(BaseModel):
    """Represent one bounded overlap packet for a single MR review run."""

    merge_request_iid: int
    current_head_sha: str
    prior_head_sha: str
    current_findings: list[ReviewFinding] = Field(default_factory=list)
    prior_findings: list[PriorReviewFinding] = Field(default_factory=list)
    candidates: list[OverlapCandidate] = Field(default_factory=list)


class OverlapResolution(BaseModel):
    """Represent one normalized overlap outcome."""

    outcome: Literal[
        "still_unresolved",
        "new_in_this_pass",
        "no_longer_present",
        "overlap_ambiguous",
    ]
    current_finding_index: int | None = None
    prior_finding_index: int | None = None
    related_prior_finding_indices: list[int] = Field(default_factory=list)


class OverlapReconciliationResult(BaseModel):
    """Represent normalized overlap outcomes for one prior-current pass pair."""

    prior_reviewed_head_sha: str
    resolutions: list[OverlapResolution] = Field(default_factory=list)
