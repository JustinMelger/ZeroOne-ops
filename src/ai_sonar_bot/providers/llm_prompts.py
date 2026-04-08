"""Prompt rendering helpers for LLM-backed workflows."""

from __future__ import annotations

from functools import cache
from importlib import resources

from ai_sonar_bot.models.analysis import IssueContext
from ai_sonar_bot.models.remediation import (
    RemediationExecutionTarget,
    remediation_profile_for,
)
from ai_sonar_bot.models.review import MergeRequestReviewContext


class LLMPromptError(RuntimeError):
    """Raised when an LLM prompt cannot be loaded or rendered."""


_PROMPT_TEMPLATE_NAMES = frozenset(
    {
        "analyze_issue.txt",
        "generate_structured_edit.txt",
        "review_merge_request.txt",
    }
)


def build_analysis_prompt(issue: RemediationExecutionTarget, context: IssueContext) -> str:
    """Build the analysis prompt for one remediation target."""
    profile = remediation_profile_for(issue)
    return render_prompt_template(
        "analyze_issue.txt",
        target_display_name=profile.target_display_name,
        source_display_name=profile.source_display_name,
        item_reference_label=profile.item_reference_label,
        issue_key=issue.source_ref,
        rule=issue.rule_id or "unknown",
        severity=issue.severity,
        issue_type=issue.issue_type or issue.source_type,
        message=issue.message,
        file_path=context.file_path,
        issue_line=context.line,
        constraints=issue.constraints or "(none)",
        snippet_start_line=context.snippet.start_line,
        snippet_end_line=context.snippet.end_line,
        full_file_included=context.full_file_included,
        context_truncated=context.truncated,
        code_snippet=context.snippet.content,
    )


def build_structured_edit_prompt(
    issue: RemediationExecutionTarget,
    context: IssueContext,
) -> str:
    """Build the structured-edit prompt for one remediation target."""
    profile = remediation_profile_for(issue)
    return render_prompt_template(
        "generate_structured_edit.txt",
        target_display_name=profile.target_display_name,
        source_display_name=profile.source_display_name,
        item_reference_label=profile.item_reference_label,
        issue_key=issue.source_ref,
        rule=issue.rule_id or "unknown",
        severity=issue.severity,
        issue_type=issue.issue_type or issue.source_type,
        message=issue.message,
        file_path=context.file_path,
        issue_line=context.line,
        constraints=issue.constraints or "(none)",
        snippet_start_line=context.snippet.start_line,
        snippet_end_line=context.snippet.end_line,
        code_snippet=context.snippet.content,
    )


def build_review_prompt(context: MergeRequestReviewContext) -> str:
    """Build the review prompt for one merge request."""
    changed_files = "\n\n".join(
        (
            f"File: {changed_file.file_path}\n"
            f"Diff:\n{changed_file.diff or '(diff unavailable)'}\n"
            f"Context lines {changed_file.start_line}-{changed_file.end_line}:\n"
            f"{changed_file.content}"
        )
        for changed_file in context.changed_files
    )
    return render_prompt_template(
        "review_merge_request.txt",
        mr_iid=context.mr_iid,
        title=context.title,
        description=context.description or "(none)",
        source_branch=context.source_branch,
        target_branch=context.target_branch,
        head_sha=context.head_sha,
        changed_files=changed_files,
    )


def render_prompt_template(name: str, **values: object) -> str:
    """Load and render one prompt template safely."""
    template = load_prompt_template(name)
    try:
        return template.format(**values)
    except KeyError as error:
        missing_key = error.args[0]
        raise LLMPromptError(
            f"Prompt template could not be rendered because `{missing_key}` is missing: {name}"
        ) from error
    except ValueError as error:
        raise LLMPromptError(
            f"Prompt template is invalid and could not be rendered: {name}"
        ) from error


@cache
def load_prompt_template(name: str) -> str:
    """Load a prompt template from the prompts directory."""
    if name not in _PROMPT_TEMPLATE_NAMES:
        raise LLMPromptError(f"Unsupported prompt template requested: {name}")
    try:
        prompts_dir = resources.files("ai_sonar_bot").joinpath("prompts")
        return prompts_dir.joinpath(name).read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError, OSError) as error:
        raise LLMPromptError(f"Prompt template file could not be read: {name}") from error
