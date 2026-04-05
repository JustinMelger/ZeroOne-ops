from pathlib import Path

from ai_sonar_bot.models.review import ReviewResult
from ai_sonar_bot.providers.llm_client import (
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
