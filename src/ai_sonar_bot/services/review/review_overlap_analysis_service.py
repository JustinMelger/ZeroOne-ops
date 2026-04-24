"""Review overlap analysis service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.review import (
    OverlapPacket,
    OverlapReconciliationResult,
    OverlapResolution,
)
from ai_sonar_bot.providers.llm_client import FixtureLLMClient, LLMClientError, OpenAILLMClient
from ai_sonar_bot.settings import SettingsError, load_openai_connection_config


@dataclass(frozen=True)
class ReviewOverlapAnalysisResult:
    """Capture the outcome of bounded review overlap analysis."""

    overlap_result: OverlapReconciliationResult | None
    status: Literal["ok", "no_backend", "llm_error", "invalid_result"]
    message: str


class ReviewOverlapAnalysisService:
    """Request bounded overlap reconciliation from the active LLM."""

    def __init__(self, config: AppConfig) -> None:
        """Initialize the review overlap analysis service."""
        self.config = config

    def analyze(self, packet: OverlapPacket) -> ReviewOverlapAnalysisResult:
        """Analyze overlap between current and prior review findings."""
        llm_client = self._build_llm_client()
        if llm_client is None:
            return ReviewOverlapAnalysisResult(
                overlap_result=None,
                status="no_backend",
                message="LLM backend not configured for review overlap reconciliation.",
            )

        try:
            overlap_result = llm_client.review_overlap_reconciliation(packet)
        except LLMClientError as error:
            return ReviewOverlapAnalysisResult(
                overlap_result=None,
                status="llm_error",
                message=f"Structured review overlap reconciliation failed: {error}",
            )

        validation_error = _validate_overlap_result(packet, overlap_result)
        if validation_error is not None:
            return ReviewOverlapAnalysisResult(
                overlap_result=None,
                status="invalid_result",
                message=(
                    "Structured review overlap reconciliation returned an invalid "
                    f"result: {validation_error}"
                ),
            )

        return ReviewOverlapAnalysisResult(
            overlap_result=overlap_result,
            status="ok",
            message=(
                f"Review overlap reconciled against prior SHA: "
                f"{overlap_result.prior_reviewed_head_sha}."
            ),
        )

    def _build_llm_client(self) -> FixtureLLMClient | OpenAILLMClient | None:
        """Build the configured overlap LLM client."""
        try:
            return OpenAILLMClient(load_openai_connection_config(), solution_output_path=None)
        except SettingsError:
            return None


def _validate_overlap_result(
    packet: OverlapPacket,
    overlap_result: OverlapReconciliationResult,
) -> str | None:
    """Return one validation error when overlap output escapes the packet boundary."""
    if overlap_result.prior_reviewed_head_sha != packet.prior_head_sha:
        return "prior reviewed SHA does not match the overlap packet"

    current_finding_count = len(packet.current_findings)
    prior_finding_count = len(packet.prior_findings)
    candidate_pairs = {
        (candidate.current_finding_index, candidate.prior_finding_index)
        for candidate in packet.candidates
    }
    seen_current_indices: set[int] = set()
    seen_prior_indices: set[int] = set()

    for resolution in overlap_result.resolutions:
        index_error = _validate_resolution_indices(
            resolution=resolution,
            current_finding_count=current_finding_count,
            prior_finding_count=prior_finding_count,
        )
        if index_error is not None:
            return index_error

        consistency_error = _validate_resolution_consistency(
            resolution=resolution,
            seen_current_indices=seen_current_indices,
            seen_prior_indices=seen_prior_indices,
        )
        if consistency_error is not None:
            return consistency_error

        if resolution.outcome == "still_unresolved":
            pair = (resolution.current_finding_index, resolution.prior_finding_index)
            if pair not in candidate_pairs:
                return "still_unresolved resolution is outside the packet candidate set"

        if resolution.outcome == "overlap_ambiguous":
            current_index = resolution.current_finding_index
            allowed_priors = {
                candidate.prior_finding_index
                for candidate in packet.candidates
                if candidate.current_finding_index == current_index
            }
            if not allowed_priors:
                return "overlap_ambiguous resolution has no bounded candidate set"
            if not set(resolution.related_prior_finding_indices).issubset(allowed_priors):
                return "overlap_ambiguous resolution references priors outside the packet"

    return None


def _validate_resolution_consistency(
    *,
    resolution: OverlapResolution,
    seen_current_indices: set[int],
    seen_prior_indices: set[int],
) -> str | None:
    """Return one validation error when overlap output reuses findings inconsistently."""
    if resolution.outcome in {"still_unresolved", "new_in_this_pass", "overlap_ambiguous"}:
        current_index = resolution.current_finding_index
        if current_index is not None:
            if current_index in seen_current_indices:
                return "current finding is referenced by multiple overlap resolutions"
            seen_current_indices.add(current_index)

    if resolution.outcome in {"still_unresolved", "no_longer_present"}:
        prior_index = resolution.prior_finding_index
        if prior_index is not None:
            if prior_index in seen_prior_indices:
                return "prior finding is referenced by multiple overlap resolutions"
            seen_prior_indices.add(prior_index)

    return None


def _validate_resolution_indices(
    *,
    resolution: OverlapResolution,
    current_finding_count: int,
    prior_finding_count: int,
) -> str | None:
    """Return one validation error when overlap indices are out of range or malformed."""
    if resolution.current_finding_index is not None and not (
        0 <= resolution.current_finding_index < current_finding_count
    ):
        return "current finding index is out of range"

    if resolution.prior_finding_index is not None and not (
        0 <= resolution.prior_finding_index < prior_finding_count
    ):
        return "prior finding index is out of range"

    for prior_index in resolution.related_prior_finding_indices:
        if not 0 <= prior_index < prior_finding_count:
            return "related prior finding index is out of range"

    if resolution.outcome == "still_unresolved":
        if resolution.current_finding_index is None or resolution.prior_finding_index is None:
            return "still_unresolved resolution must reference one current and one prior finding"

    if resolution.outcome == "new_in_this_pass":
        if resolution.current_finding_index is None or resolution.prior_finding_index is not None:
            return "new_in_this_pass resolution must reference only one current finding"

    if resolution.outcome == "no_longer_present":
        if resolution.current_finding_index is not None or resolution.prior_finding_index is None:
            return "no_longer_present resolution must reference only one prior finding"

    if resolution.outcome == "overlap_ambiguous":
        if resolution.current_finding_index is None:
            return "overlap_ambiguous resolution must reference one current finding"
        if not resolution.related_prior_finding_indices:
            return "overlap_ambiguous resolution must reference related prior findings"
        if resolution.prior_finding_index is not None:
            return "overlap_ambiguous resolution must not set one direct prior finding"

    return None
