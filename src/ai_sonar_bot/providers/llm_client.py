"""LLM client.

This module will provide structured issue analysis and patch generation through
an LLM provider.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openai import OpenAI

from ai_sonar_bot.models.analysis import (
    IssueAnalysis,
    IssueContext,
    PatchProposal,
    StructuredEditProposal,
)
from ai_sonar_bot.models.config import OpenAIConnectionConfig
from ai_sonar_bot.models.review import MergeRequestReviewContext, ReviewResult
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.utils.files import ensure_parent


class LLMClientError(RuntimeError):
    """Raised when LLM analysis or patch generation fails."""


class LLMClient:
    """Placeholder LLM client for the initial scaffold."""

    def analyze_issue(self, issue: SonarIssue, context: IssueContext) -> IssueAnalysis:
        """Analyze a SonarQube issue.

        Args:
            issue: Issue to analyze.
            context: Repository context for the issue.

        Returns:
            Structured issue analysis.
        """
        raise NotImplementedError("LLM integration is not implemented yet.")

    def generate_structured_edit(
        self,
        issue: SonarIssue,
        context: IssueContext,
    ) -> StructuredEditProposal:
        """Generate a narrow structured edit proposal.

        Args:
            issue: Issue to fix.
            context: Repository context for the issue.

        Returns:
            Structured edit proposal for bot-rendered diffs.

        Raises:
            LLMClientError: If structured edit generation is unsupported or fails.
        """
        raise NotImplementedError("Structured edit generation is not implemented yet.")

    def review_merge_request(self, context: MergeRequestReviewContext) -> ReviewResult:
        """Review one merge request and return structured findings."""
        raise NotImplementedError("Merge request review is not implemented yet.")


class OpenAILLMClient(LLMClient):
    """LLM client backed by the official OpenAI Python SDK.

    Args:
        config: OpenAI connection settings.
    """

    def __init__(
        self,
        config: OpenAIConnectionConfig,
        solution_output_path: Path | None,
    ) -> None:
        """Initialize the OpenAI-backed LLM client.

        Args:
            config: OpenAI connection settings.
            solution_output_path: File path where OpenAI outputs should be written.
        """
        self.config = config
        self.solution_output_path = solution_output_path
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)

    def analyze_issue(self, issue: SonarIssue, context: IssueContext) -> IssueAnalysis:
        """Analyze a SonarQube issue with OpenAI.

        Args:
            issue: Issue to analyze.
            context: Repository context for the issue.

        Returns:
            Structured issue analysis.

        Raises:
            LLMClientError: If the API call fails or returns an invalid payload.
        """
        input_text = _build_analysis_prompt(issue, context)
        try:
            response = self.client.responses.parse(
                model=self.config.model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You analyze SonarQube issues and return strictly structured JSON."
                        ),
                    },
                    {"role": "user", "content": input_text},
                ],
                text_format=IssueAnalysis,
            )
        except Exception as error:
            raise LLMClientError("OpenAI issue analysis request failed.") from error

        if response.output_parsed is None:
            raise LLMClientError("OpenAI issue analysis did not return parsed output.")
        analysis = response.output_parsed
        if self.solution_output_path is not None:
            _write_solution_file(
                self.solution_output_path,
                issue_key=issue.key,
                analysis=analysis,
            )
        return analysis

    def generate_structured_edit(
        self,
        issue: SonarIssue,
        context: IssueContext,
    ) -> StructuredEditProposal:
        """Generate a structured edit proposal with OpenAI.

        Args:
            issue: Issue to fix.
            context: Repository context for the issue.

        Returns:
            Structured edit proposal.

        Raises:
            LLMClientError: If the API call fails or returns invalid output.
        """
        input_text = _build_structured_edit_prompt(issue, context)
        try:
            response = self.client.responses.parse(
                model=self.config.model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You propose exact file edits for SonarQube issues and return "
                            "strictly structured JSON."
                        ),
                    },
                    {"role": "user", "content": input_text},
                ],
                text_format=StructuredEditProposal,
            )
        except Exception as error:
            raise LLMClientError("OpenAI structured edit generation request failed.") from error

        if response.output_parsed is None:
            raise LLMClientError("OpenAI structured edit generation did not return parsed output.")
        return response.output_parsed

    def review_merge_request(self, context: MergeRequestReviewContext) -> ReviewResult:
        """Review a merge request with OpenAI."""
        input_text = _build_review_prompt(context)
        try:
            response = self.client.responses.parse(
                model=self.config.model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You review merge requests and return strictly structured "
                            "JSON findings."
                        ),
                    },
                    {"role": "user", "content": input_text},
                ],
                text_format=ReviewResult,
            )
        except Exception as error:
            raise LLMClientError("OpenAI merge request review request failed.") from error

        if response.output_parsed is None:
            raise LLMClientError("OpenAI merge request review did not return parsed output.")
        return response.output_parsed


class FixtureLLMClient(LLMClient):
    """LLM client backed by a local analysis fixture file.

    Args:
        analysis_fixture_path: Path to a local JSON analysis fixture.
        structured_edit_fixture_path: Optional path to a local JSON structured edit fixture.
    """

    def __init__(
        self,
        analysis_fixture_path: Path,
        structured_edit_fixture_path: Path | None = None,
        review_fixture_path: Path | None = None,
    ) -> None:
        """Initialize the fixture-backed LLM client.

        Args:
            analysis_fixture_path: Path to a local JSON analysis fixture.
            structured_edit_fixture_path: Optional path to a local JSON structured edit fixture.
            review_fixture_path: Optional path to a local JSON review fixture.
        """
        self.analysis_fixture_path = analysis_fixture_path
        self.structured_edit_fixture_path = structured_edit_fixture_path
        self.review_fixture_path = review_fixture_path

    def analyze_issue(self, issue: SonarIssue, context: IssueContext) -> IssueAnalysis:
        """Load a fixture-based issue analysis result.

        Args:
            issue: Issue to analyze.
            context: Repository context for the issue.

        Returns:
            Structured issue analysis from the fixture.
        """
        del issue, context
        return load_analysis_fixture(self.analysis_fixture_path)

    def generate_structured_edit(
        self,
        issue: SonarIssue,
        context: IssueContext,
    ) -> StructuredEditProposal:
        """Load a fixture-based structured edit result.

        Args:
            issue: Issue to fix.
            context: Repository context for the issue.

        Returns:
            Structured edit proposal from the fixture.
        """
        del issue, context
        if self.structured_edit_fixture_path is None:
            raise LLMClientError("LLM structured edit fixture path is not configured.")
        return load_structured_edit_fixture(self.structured_edit_fixture_path)

    def review_merge_request(self, context: MergeRequestReviewContext) -> ReviewResult:
        """Load a fixture-based review result."""
        del context
        if self.review_fixture_path is None:
            raise LLMClientError("LLM review fixture path is not configured.")
        return load_review_fixture(self.review_fixture_path)


def load_analysis_fixture(path: Path) -> IssueAnalysis:
    """Load an issue analysis result from a JSON fixture.

    Args:
        path: Path to the analysis fixture.

    Returns:
        Structured issue analysis.

    Raises:
        LLMClientError: If the fixture file is missing or invalid.
    """
    if not path.exists():
        raise LLMClientError(f"LLM analysis fixture file not found: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise LLMClientError(f"LLM analysis fixture file is invalid JSON: {path}") from error

    if not isinstance(payload, dict):
        raise LLMClientError("Unexpected LLM analysis fixture payload.")

    try:
        return IssueAnalysis.model_validate(payload)
    except Exception as error:
        raise LLMClientError("Invalid LLM analysis fixture structure.") from error


def load_structured_edit_fixture(path: Path) -> StructuredEditProposal:
    """Load a structured edit proposal result from a JSON fixture.

    Args:
        path: Path to the structured edit fixture.

    Returns:
        Structured edit proposal.

    Raises:
        LLMClientError: If the fixture file is missing or invalid.
    """
    if not path.exists():
        raise LLMClientError(f"LLM structured edit fixture file not found: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise LLMClientError(f"LLM structured edit fixture file is invalid JSON: {path}") from error

    if not isinstance(payload, dict):
        raise LLMClientError("Unexpected LLM structured edit fixture payload.")

    try:
        return StructuredEditProposal.model_validate(payload)
    except Exception as error:
        raise LLMClientError("Invalid LLM structured edit fixture structure.") from error


def load_review_fixture(path: Path) -> ReviewResult:
    """Load a structured review result from a JSON fixture."""
    if not path.exists():
        raise LLMClientError(f"LLM review fixture file not found: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise LLMClientError(f"LLM review fixture file is invalid JSON: {path}") from error

    if not isinstance(payload, dict):
        raise LLMClientError("Unexpected LLM review fixture payload.")

    try:
        return ReviewResult.model_validate(payload)
    except Exception as error:
        raise LLMClientError("Invalid LLM review fixture structure.") from error


def _write_solution_file(
    path: Path,
    *,
    issue_key: str,
    analysis: IssueAnalysis | None = None,
    structured_edit: StructuredEditProposal | None = None,
    patch: PatchProposal | None = None,
    decision: str | None = None,
    rejection_reason: str | None = None,
    clear_patch: bool = False,
) -> None:
    """Write OpenAI outputs to a local JSON file.

    Args:
        path: Output file path.
        issue_key: SonarQube issue key.
        analysis: Optional structured issue analysis.
        structured_edit: Optional structured edit proposal.
        patch: Optional structured patch proposal.
        decision: Optional decision for the solution artifact.
        rejection_reason: Optional rejection reason for the solution artifact.
        clear_patch: Whether to remove any existing patch from the artifact.
    """
    ensure_parent(path)
    payload = _load_existing_solution(path)
    payload["issue_key"] = issue_key
    if analysis is not None:
        payload["analysis"] = analysis.model_dump(mode="json")
    if structured_edit is not None:
        payload["structured_edit"] = structured_edit.model_dump(mode="json")
    if clear_patch:
        payload.pop("patch", None)
    if patch is not None:
        payload["patch"] = patch.model_dump(mode="json")
    if decision is not None:
        payload["decision"] = decision
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    elif decision != "rejected":
        payload.pop("rejection_reason", None)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _load_existing_solution(path: Path) -> dict[str, Any]:
    """Load an existing solution file if present.

    Args:
        path: Output file path.

    Returns:
        Existing JSON payload, or an empty dictionary.
    """
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_analysis_prompt(issue: SonarIssue, context: IssueContext) -> str:
    """Build the analysis prompt for OpenAI.

    Args:
        issue: SonarQube issue to analyze.
        context: Focused code context.

    Returns:
        Prompt text for structured issue analysis.
    """
    return (
        "Analyze the following SonarQube issue and return structured JSON.\n\n"
        f"Issue key: {issue.key}\n"
        f"Rule: {issue.rule}\n"
        f"Severity: {issue.severity}\n"
        f"Type: {issue.type}\n"
        f"Message: {issue.message}\n"
        f"File path: {context.file_path}\n"
        f"Issue line: {context.line}\n"
        f"Snippet start line: {context.snippet.start_line}\n"
        f"Snippet end line: {context.snippet.end_line}\n"
        f"Full file included: {context.full_file_included}\n"
        f"Context truncated: {context.truncated}\n\n"
        "Code snippet:\n"
        f"{context.snippet.content}\n"
    )


def _build_structured_edit_prompt(issue: SonarIssue, context: IssueContext) -> str:
    """Build the structured-edit prompt for OpenAI.

    Args:
        issue: SonarQube issue to fix.
        context: Focused code context.

    Returns:
        Prompt text for structured edit generation.
    """
    return (
        "Generate a minimal exact text edit for the following SonarQube issue and return "
        "structured JSON.\n\n"
        f"Issue key: {issue.key}\n"
        f"Rule: {issue.rule}\n"
        f"Severity: {issue.severity}\n"
        f"Type: {issue.type}\n"
        f"Message: {issue.message}\n"
        f"File path: {context.file_path}\n"
        f"Issue line: {context.line}\n"
        f"Snippet start line: {context.snippet.start_line}\n"
        f"Snippet end line: {context.snippet.end_line}\n\n"
        "Requirements:\n"
        "- Return exactly one edit for one repository-relative file.\n"
        "- Use exact existing source text in `search_text`.\n"
        "- Keep the change minimal and scoped to the issue.\n"
        "- Use `line_hint` when the same text may appear more than once.\n"
        "- Do not return a unified diff.\n\n"
        "Code snippet:\n"
        f"{context.snippet.content}\n"
    )


def _build_review_prompt(context: MergeRequestReviewContext) -> str:
    """Build the review prompt for OpenAI."""
    changed_files = "\n\n".join(
        (
            f"File: {changed_file.file_path}\n"
            f"Diff:\n{changed_file.diff or '(diff unavailable)'}\n"
            f"Context lines {changed_file.start_line}-{changed_file.end_line}:\n"
            f"{changed_file.content}"
        )
        for changed_file in context.changed_files
    )
    return (
        "Review the merge request and return structured JSON only.\n\n"
        "Focus on bugs, regressions, missing validation, and unsafe assumptions.\n"
        "Return classification `no_findings` when nothing actionable stands out.\n"
        "Return classification `manual_review_only` when the provided context is insufficient.\n\n"
        f"Merge request IID: {context.mr_iid}\n"
        f"Title: {context.title}\n"
        f"Description: {context.description or '(none)'}\n"
        f"Source branch: {context.source_branch}\n"
        f"Target branch: {context.target_branch}\n"
        f"Head SHA: {context.head_sha}\n\n"
        "Changed files:\n"
        f"{changed_files}\n"
    )
