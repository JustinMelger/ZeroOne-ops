"""Build bounded overlap packets for repeated-review reconciliation."""

from __future__ import annotations

import re

from zeroone_ops.models.review import (
    MergeRequestReviewContext,
    OverlapCandidate,
    OverlapPacket,
    PriorReviewFinding,
    ReviewFinding,
    ReviewResult,
)
from zeroone_ops.utils.review_finding_identity import (
    build_legacy_review_finding_identity,
    build_review_finding_identity,
)

_MIN_SHARED_TITLE_TOKENS = 2
_MIN_TITLE_TOKEN_OVERLAP = 0.6


class OverlapPacketBuilder:
    """Build app-owned overlap packets for one MR review run."""

    def build(
        self,
        *,
        context: MergeRequestReviewContext,
        review_result: ReviewResult,
    ) -> OverlapPacket | None:
        """Build one bounded overlap packet for the latest prior review pass."""
        prior_review_context = context.prior_review_context
        if not prior_review_context or not prior_review_context.passes:
            return None

        latest_prior_pass = prior_review_context.passes[0]
        candidates: list[OverlapCandidate] = []
        for current_index, current_finding in enumerate(review_result.findings):
            for prior_index, prior_finding in self._candidate_prior_findings(
                current_finding=current_finding,
                prior_findings=latest_prior_pass.findings,
            ):
                candidates.append(
                    OverlapCandidate(
                        current_finding_index=current_index,
                        prior_finding_index=prior_index,
                        reasons=self._candidate_reasons(
                            current_finding=current_finding,
                            prior_finding=prior_finding,
                        ),
                    )
                )

        return OverlapPacket(
            merge_request_iid=context.mr_iid,
            current_head_sha=context.head_sha,
            prior_head_sha=latest_prior_pass.reviewed_head_sha,
            current_findings=review_result.findings,
            prior_findings=latest_prior_pass.findings,
            candidates=candidates,
        )

    def _candidate_prior_findings(
        self,
        *,
        current_finding: ReviewFinding,
        prior_findings: list[PriorReviewFinding],
    ) -> list[tuple[int, PriorReviewFinding]]:
        """Return a bounded set of prior findings for one current finding."""
        current_identity = build_review_finding_identity(current_finding)
        current_legacy_identity = build_legacy_review_finding_identity(current_finding)
        current_key = self._current_finding_key(current_finding)

        identity_matches = [
            (index, prior_finding)
            for index, prior_finding in enumerate(prior_findings)
            if prior_finding.identity is not None and prior_finding.identity == current_identity
        ]
        if identity_matches:
            return identity_matches

        legacy_identity_matches = [
            (index, prior_finding)
            for index, prior_finding in enumerate(prior_findings)
            if current_legacy_identity in {prior_finding.identity, prior_finding.legacy_identity}
        ]
        if legacy_identity_matches:
            return legacy_identity_matches

        exact_key_matches = [
            (index, prior_finding)
            for index, prior_finding in enumerate(prior_findings)
            if prior_finding.legacy_identity is None
            and self._prior_finding_key(prior_finding) == current_key
        ]
        if exact_key_matches:
            return exact_key_matches

        current_file_path = self._normalized_file_path(current_finding.file_path)
        same_file_candidates = [
            (index, prior_finding)
            for index, prior_finding in enumerate(prior_findings)
            if self._normalized_file_path(self._prior_file_path(prior_finding)) == current_file_path
        ]
        if not same_file_candidates:
            return []

        narrowed_candidates = self._narrow_candidates_by_field(
            same_file_candidates,
            field_name="symbol",
            expected_value=current_finding.symbol,
        )
        narrowed_candidates = self._narrow_candidates_by_field(
            narrowed_candidates,
            field_name="issue_kind",
            expected_value=current_finding.issue_kind,
        )
        narrowed_candidates = self._narrow_candidates_by_field(
            narrowed_candidates,
            field_name="region_hint",
            expected_value=current_finding.region_hint,
        )
        return narrowed_candidates

    def _candidate_reasons(
        self,
        *,
        current_finding: ReviewFinding,
        prior_finding: PriorReviewFinding,
    ) -> list[str]:
        """Explain why one prior finding became an overlap candidate."""
        current_identity = build_review_finding_identity(current_finding)
        current_legacy_identity = build_legacy_review_finding_identity(current_finding)
        current_key = self._current_finding_key(current_finding)

        if prior_finding.identity is not None and prior_finding.identity == current_identity:
            return ["canonical_identity"]
        if current_legacy_identity in {prior_finding.identity, prior_finding.legacy_identity}:
            return ["legacy_identity"]
        if (
            prior_finding.legacy_identity is None
            and self._prior_finding_key(prior_finding) == current_key
        ):
            return ["exact_summary_key"]

        reasons = ["same_file"]
        if current_finding.symbol is not None and prior_finding.symbol == current_finding.symbol:
            reasons.append("symbol")
        if (
            current_finding.issue_kind is not None
            and prior_finding.issue_kind == current_finding.issue_kind
        ):
            reasons.append("issue_kind")
        if (
            current_finding.region_hint is not None
            and prior_finding.region_hint == current_finding.region_hint
        ):
            reasons.append("region_hint")

        prior_title = self._prior_title(prior_finding)
        if prior_title is not None and self._titles_look_like_same_finding(
            current_finding.title, prior_title
        ):
            reasons.append("title_overlap")
        return reasons

    def _narrow_candidates_by_field(
        self,
        candidates: list[tuple[int, PriorReviewFinding]],
        *,
        field_name: str,
        expected_value: str | None,
    ) -> list[tuple[int, PriorReviewFinding]]:
        """Return a narrower candidate set when one structured field matches."""
        if expected_value is None:
            return candidates

        matching_candidates = [
            candidate
            for candidate in candidates
            if getattr(candidate[1], field_name) == expected_value
        ]
        if matching_candidates:
            return matching_candidates

        candidates_with_structured_value = [
            candidate for candidate in candidates if getattr(candidate[1], field_name) is not None
        ]
        if candidates_with_structured_value:
            return []
        return candidates

    def _current_finding_key(self, finding: ReviewFinding) -> tuple[str, str, str]:
        """Build a conservative key for one current finding."""
        summary = f"{finding.file_path}: {finding.title}"
        return (
            finding.file_path.strip().lower(),
            finding.title.strip().lower(),
            self._normalize_finding_text(summary),
        )

    def _prior_finding_key(self, finding: PriorReviewFinding) -> tuple[str, str, str] | None:
        """Build a conservative key for one persisted prior finding."""
        file_path = finding.file_path
        title = finding.title
        if file_path is None or title is None:
            parsed = self._split_prior_summary(finding.summary)
            if parsed is None:
                return None
            file_path, title = parsed
        if not file_path.strip() or not title.strip():
            return None
        return (
            file_path.strip().lower(),
            title.strip().lower(),
            self._normalize_finding_text(f"{file_path}: {title}"),
        )

    def _prior_file_path(self, finding: PriorReviewFinding) -> str | None:
        """Extract the normalized file path from one prior finding summary."""
        if finding.file_path is not None:
            return finding.file_path
        parsed = self._split_prior_summary(finding.summary)
        return parsed[0] if parsed is not None else None

    def _prior_title(self, finding: PriorReviewFinding) -> str | None:
        """Extract the normalized title from one prior finding summary."""
        if finding.title is not None:
            return finding.title
        parsed = self._split_prior_summary(finding.summary)
        return parsed[1] if parsed is not None else None

    def _split_prior_summary(self, summary: str) -> tuple[str, str] | None:
        """Split a normalized prior finding summary into path and title."""
        path, separator, title = summary.partition(": ")
        if separator == "":
            return None
        normalized_path = path.strip()
        normalized_title = title.strip()
        if not normalized_path or not normalized_title:
            return None
        return normalized_path, normalized_title

    def _normalize_finding_text(self, text: str) -> str:
        """Normalize one finding string for bounded exact fallback matching."""
        lowered = text.lower()
        normalized = re.sub(r"[^a-z0-9]+", " ", lowered)
        return re.sub(r"\s+", " ", normalized).strip()

    def _normalized_file_path(self, file_path: str | None) -> str | None:
        """Return a normalized file path for candidate narrowing."""
        if file_path is None:
            return None
        return file_path.strip().lower()

    def _titles_look_like_same_finding(self, current_title: str, prior_title: str) -> bool:
        """Return whether two titles likely describe the same finding."""
        current_tokens = self._title_tokens(current_title)
        prior_tokens = self._title_tokens(prior_title)
        if not current_tokens or not prior_tokens:
            return False

        shared_tokens = current_tokens & prior_tokens
        if len(shared_tokens) < _MIN_SHARED_TITLE_TOKENS:
            return False

        smaller_token_count = min(len(current_tokens), len(prior_tokens))
        return len(shared_tokens) / smaller_token_count >= _MIN_TITLE_TOKEN_OVERLAP

    def _title_tokens(self, title: str) -> set[str]:
        """Extract lightly normalized title tokens for conservative fuzzy matching."""
        tokens: set[str] = set()
        for token in re.findall(r"[a-z0-9_]+", title.lower()):
            normalized = self._normalize_title_token(token)
            if len(normalized) >= 4:
                tokens.add(normalized)
        return tokens

    def _normalize_title_token(self, token: str) -> str:
        """Lightly normalize title tokens so small wording drift still matches."""
        if token.endswith("ing") and len(token) > 5:
            return token[:-3]
        if token.endswith("ed") and len(token) > 4:
            return token[:-2]
        if token.endswith("ion") and len(token) > 5:
            return token[:-3]
        return token
