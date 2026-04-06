"""LLM client.

This module will provide structured issue analysis and patch generation through
an LLM provider.
"""

from __future__ import annotations

import json
from importlib import resources
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
    return _load_prompt_template("analyze_issue.txt").format(
        issue_key=issue.key,
        rule=issue.rule,
        severity=issue.severity,
        issue_type=issue.type,
        message=issue.message,
        file_path=context.file_path,
        issue_line=context.line,
        snippet_start_line=context.snippet.start_line,
        snippet_end_line=context.snippet.end_line,
        full_file_included=context.full_file_included,
        context_truncated=context.truncated,
        code_snippet=context.snippet.content,
    )


def _build_structured_edit_prompt(issue: SonarIssue, context: IssueContext) -> str:
    """Build the structured-edit prompt for OpenAI.

    Args:
        issue: SonarQube issue to fix.
        context: Focused code context.

    Returns:
        Prompt text for structured edit generation.
    """
    return _load_prompt_template("generate_structured_edit.txt").format(
        issue_key=issue.key,
        rule=issue.rule,
        severity=issue.severity,
        issue_type=issue.type,
        message=issue.message,
        file_path=context.file_path,
        issue_line=context.line,
        snippet_start_line=context.snippet.start_line,
        snippet_end_line=context.snippet.end_line,
        code_snippet=context.snippet.content,
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
    return _load_prompt_template("review_merge_request.txt").format(
        mr_iid=context.mr_iid,
        title=context.title,
        description=context.description or "(none)",
        source_branch=context.source_branch,
        target_branch=context.target_branch,
        head_sha=context.head_sha,
        changed_files=changed_files,
    )


def _load_prompt_template(name: str) -> str:
    """Load a prompt template from the prompts directory."""
    try:
        return resources.files("ai_sonar_bot").joinpath("prompts", name).read_text(encoding="utf-8")
    except OSError as error:
        raise LLMClientError(f"Prompt template file could not be read: {name}") from error
