from pathlib import Path

from ai_sonar_bot.models.analysis import CodeContextSnippet, IssueContext
from ai_sonar_bot.models.review import MergeRequestReviewContext, ReviewFileContext, ReviewResult
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.providers.llm_client import (
    _build_analysis_prompt,
    _build_review_prompt,
    _build_structured_edit_prompt,
    load_analysis_fixture,
    load_review_fixture,
    load_structured_edit_fixture,
)


def test_load_analysis_fixture_returns_issue_analysis(tmp_path: Path) -> None:
    fixture_path = tmp_path / "analysis.json"
    fixture_path.write_text(
        """
        {
          "issue_key": "AX1",
          "classification": "auto_fixable",
          "summary": "Summary",
          "risk_notes": ["risk"],
          "target_files": ["src/service.py"],
          "proposed_strategy": "Do the small safe change."
        }
        """.strip(),
        encoding="utf-8",
    )

    analysis = load_analysis_fixture(fixture_path)

    assert analysis.issue_key == "AX1"
    assert analysis.classification.value == "auto_fixable"
    assert analysis.target_files == ["src/service.py"]


def test_load_structured_edit_fixture_returns_proposal(tmp_path: Path) -> None:
    fixture_path = tmp_path / "edit.json"
    fixture_path.write_text(
        """
        {
          "issue_key": "AX1",
          "edits": [
            {
              "file_path": "src/service.py",
              "search_text": "value = 1",
              "replace_text": "value = 2",
              "line_hint": 1
            }
          ],
          "commit_message": "fix(sonar): update service [AX1]",
          "mr_title": "fix: update service",
          "mr_description": "summary"
        }
        """.strip(),
        encoding="utf-8",
    )

    proposal = load_structured_edit_fixture(fixture_path)

    assert proposal.issue_key == "AX1"
    assert proposal.edits[0].file_path == "src/service.py"
    assert proposal.mr_title == "fix: update service"


def test_load_review_fixture_returns_review_result(tmp_path: Path) -> None:
    fixture_path = tmp_path / "review.json"
    fixture_path.write_text(
        """
        {
          "classification": "findings_present",
          "summary": "One medium-risk finding.",
          "findings": [
            {
              "severity": "medium",
              "file_path": "src/service.py",
              "title": "Missing test coverage",
              "explanation": "The change alters branch behavior without test updates.",
              "suggested_follow_up": "Add a regression test for the changed branch."
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    review = load_review_fixture(fixture_path)

    assert isinstance(review, ReviewResult)
    assert review.classification == "findings_present"
    assert review.findings[0].file_path == "src/service.py"


def test_build_analysis_prompt_uses_prompt_template() -> None:
    issue = SonarIssue(
        key="AX1",
        rule="python:S100",
        severity="MAJOR",
        type="CODE_SMELL",
        status="OPEN",
        message="Rename this function.",
        component="project:src/service.py",
        project="project",
        file_path="src/service.py",
    )
    context = IssueContext(
        issue_key="AX1",
        file_path="src/service.py",
        line=8,
        file_size_bytes=128,
        snippet=CodeContextSnippet(
            start_line=4,
            end_line=12,
            content="def bad_name():\n    return 1\n",
        ),
        full_file_included=False,
        truncated=True,
    )

    prompt = _build_analysis_prompt(issue, context)

    assert "Issue key: AX1" in prompt
    assert "This workflow only supports low-risk single-file fixes." in prompt
    assert "Code snippet:\ndef bad_name():\n    return 1\n" in prompt


def test_build_structured_edit_prompt_uses_prompt_template() -> None:
    issue = SonarIssue(
        key="AX1",
        rule="python:S100",
        severity="MAJOR",
        type="CODE_SMELL",
        status="OPEN",
        message="Rename this function.",
        component="project:src/service.py",
        project="project",
        file_path="src/service.py",
    )
    context = IssueContext(
        issue_key="AX1",
        file_path="src/service.py",
        line=8,
        file_size_bytes=128,
        snippet=CodeContextSnippet(
            start_line=4,
            end_line=12,
            content="def bad_name():\n    return 1\n",
        ),
        full_file_included=False,
        truncated=False,
    )

    prompt = _build_structured_edit_prompt(issue, context)

    assert "Generate a minimal exact text edit" in prompt
    assert "Return exactly one edit for one repository-relative file." in prompt
    assert "File path: src/service.py" in prompt


def test_build_review_prompt_uses_prompt_template() -> None:
    context = MergeRequestReviewContext(
        mr_iid=17,
        title="feat: add safety check",
        description="Adds validation.",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1 +1 @@\n-value = 1\n+value = 2",
                content="value = 2\n",
                start_line=1,
                end_line=1,
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    prompt = _build_review_prompt(context)

    assert "Review the merge request and return structured JSON only." in prompt
    assert "Merge request IID: 17" in prompt
    assert "File: src/service.py" in prompt
