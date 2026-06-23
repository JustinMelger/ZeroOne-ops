"""Review artifact validator."""

from __future__ import annotations

from zeroone_ops.models.review import (
    ArtifactValidationIssue,
    ArtifactValidationResult,
    PublishableReviewArtifact,
)


class ReviewArtifactValidator:
    """Validate publish-shaped review artifacts for strict structural invariants."""

    def validate(self, artifact: PublishableReviewArtifact) -> ArtifactValidationResult:
        """Validate one publish-shaped review artifact."""
        issues = self._validate_findings_presence(artifact)
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
        if artifact.classification == "manual_review_only" and artifact.findings:
            return [
                ArtifactValidationIssue(
                    rule_id="manual_review_only_with_findings",
                    message="Artifact classification is manual_review_only but findings exist.",
                )
            ]
        return []
