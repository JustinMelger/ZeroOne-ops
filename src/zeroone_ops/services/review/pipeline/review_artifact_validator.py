"""Review artifact validator."""

from __future__ import annotations

from zeroone_ops.models.review import (
    ArtifactValidationIssue,
    ArtifactValidationResult,
    PublishableReviewArtifact,
)

_NO_FINDINGS_PHRASES = (
    "no actionable findings",
    "no findings",
)
_ACTIONABLE_CONCERN_PHRASES = (
    "actionable concern",
    "actionable issue",
    "deterministic runtime error",
    "missing validation",
    "this regression",
    "the regression",
    "this bug",
    "the bug",
    "runtime error",
    "breaks runtime behavior",
    "breaks behavior",
    "breaks the",
    "broken behavior",
)


class ReviewArtifactValidator:
    """Validate publish-shaped review artifacts for narrow contradiction classes."""

    def validate(self, artifact: PublishableReviewArtifact) -> ArtifactValidationResult:
        """Validate one publish-shaped review artifact."""
        issues = [
            *self._validate_findings_presence(artifact),
            *self._validate_summary_contradictions(artifact),
            *self._validate_reason_contradictions(artifact),
        ]
        if issues:
            return ArtifactValidationResult(
                status="rejected",
                issues=issues,
                artifact=artifact,
            )
        return ArtifactValidationResult(
            status="valid",
            issues=[],
            artifact=artifact,
        )

    def build_manual_review_only_fallback(
        self,
        *,
        artifact: PublishableReviewArtifact,
        validation_result: ArtifactValidationResult,
    ) -> PublishableReviewArtifact:
        """Build a bounded fallback artifact when normal publish is not trustworthy."""
        issue_messages = "; ".join(issue.message for issue in validation_result.issues)
        return PublishableReviewArtifact(
            classification="manual_review_only",
            summary=(
                "The automated review produced an internally inconsistent artifact and "
                "was downgraded to manual review."
            ),
            review_confidence=artifact.review_confidence,
            review_confidence_reason=issue_messages or artifact.review_confidence_reason,
            findings=[],
            follow_up_lines=list(artifact.follow_up_lines),
        )

    def _validate_findings_presence(
        self,
        artifact: PublishableReviewArtifact,
    ) -> list[ArtifactValidationIssue]:
        """Reject impossible classification/finding-count combinations."""
        if artifact.classification == "findings_present" and not artifact.findings:
            return [
                ArtifactValidationIssue(
                    rule_id="findings_present_without_findings",
                    message="Artifact classification is findings_present but no findings exist.",
                )
            ]
        if artifact.classification == "no_findings" and artifact.findings:
            return [
                ArtifactValidationIssue(
                    rule_id="no_findings_with_findings",
                    message="Artifact classification is no_findings but findings are present.",
                )
            ]
        return []

    def _validate_summary_contradictions(
        self,
        artifact: PublishableReviewArtifact,
    ) -> list[ArtifactValidationIssue]:
        """Reject high-trust summary contradictions."""
        normalized_summary = artifact.summary.lower()
        if artifact.classification == "findings_present" and any(
            phrase in normalized_summary for phrase in _NO_FINDINGS_PHRASES
        ):
            return [
                ArtifactValidationIssue(
                    rule_id="findings_present_summary_denies_findings",
                    message="Artifact summary claims there are no actionable findings.",
                )
            ]
        if artifact.classification == "no_findings" and any(
            phrase in normalized_summary for phrase in _ACTIONABLE_CONCERN_PHRASES
        ):
            return [
                ArtifactValidationIssue(
                    rule_id="no_findings_summary_describes_concern",
                    message="Artifact summary still describes an actionable concern.",
                )
            ]
        return []

    def _validate_reason_contradictions(
        self,
        artifact: PublishableReviewArtifact,
    ) -> list[ArtifactValidationIssue]:
        """Reject narrow confidence-reason contradictions."""
        if artifact.review_confidence_reason is None:
            return []
        normalized_reason = artifact.review_confidence_reason.lower()
        if artifact.classification == "no_findings" and any(
            phrase in normalized_reason for phrase in _ACTIONABLE_CONCERN_PHRASES
        ):
            return [
                ArtifactValidationIssue(
                    rule_id="no_findings_reason_describes_concern",
                    message="Artifact confidence reason still describes an actionable concern.",
                )
            ]
        if artifact.classification == "findings_present" and any(
            phrase in normalized_reason for phrase in _NO_FINDINGS_PHRASES
        ):
            return [
                ArtifactValidationIssue(
                    rule_id="findings_present_reason_denies_findings",
                    message="Artifact confidence reason denies the accepted findings.",
                )
            ]
        return []
