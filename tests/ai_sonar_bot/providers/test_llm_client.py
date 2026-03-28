from pathlib import Path

from ai_sonar_bot.providers.llm_client import load_analysis_fixture, load_patch_fixture


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


def test_load_patch_fixture_returns_patch_proposal(tmp_path: Path) -> None:
    fixture_path = tmp_path / "patch.json"
    fixture_path.write_text(
        """
        {
          "issue_key": "AX1",
          "files_touched": ["src/service.py"],
          "unified_diff": "diff --git a/src/service.py b/src/service.py\\n",
          "commit_message": "fix(sonar): update service [AX1]",
          "mr_title": "fix: update service",
          "mr_description": "summary"
        }
        """.strip(),
        encoding="utf-8",
    )

    patch = load_patch_fixture(fixture_path)

    assert patch.issue_key == "AX1"
    assert patch.files_touched == ["src/service.py"]
    assert patch.mr_title == "fix: update service"
