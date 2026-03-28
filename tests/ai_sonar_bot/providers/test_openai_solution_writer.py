from pathlib import Path

from ai_sonar_bot.models.analysis import AnalysisClassification, IssueAnalysis, PatchProposal
from ai_sonar_bot.providers.llm_client import _write_solution_file


def test_write_solution_file_persists_analysis_and_patch(tmp_path: Path) -> None:
    output_path = tmp_path / "artifacts" / "openai-solution.json"
    analysis = IssueAnalysis(
        issue_key="AX1",
        classification=AnalysisClassification.AUTO_FIXABLE,
        summary="Summary",
        risk_notes=[],
        target_files=["src/service.py"],
        proposed_strategy="Make the minimal fix.",
    )
    patch = PatchProposal(
        issue_key="AX1",
        files_touched=["src/service.py"],
        unified_diff="diff --git a/src/service.py b/src/service.py\n",
        commit_message="fix(sonar): update service [AX1]",
        mr_title="fix: update service",
        mr_description="summary",
    )

    _write_solution_file(output_path, issue_key="AX1", analysis=analysis)
    _write_solution_file(output_path, issue_key="AX1", patch=patch)

    payload = output_path.read_text(encoding="utf-8")

    assert output_path.exists()
    assert '"issue_key": "AX1"' in payload
    assert '"summary": "Summary"' in payload
    assert '"mr_title": "fix: update service"' in payload


def test_write_solution_file_can_record_rejection_and_clear_patch(tmp_path: Path) -> None:
    output_path = tmp_path / "artifacts" / "openai-solution.json"
    patch = PatchProposal(
        issue_key="AX1",
        files_touched=["src/service.py"],
        unified_diff="diff --git a/src/service.py b/src/service.py\n",
        commit_message="fix(sonar): update service [AX1]",
        mr_title="fix: update service",
        mr_description="summary",
    )

    _write_solution_file(output_path, issue_key="AX1", patch=patch)
    _write_solution_file(
        output_path,
        issue_key="AX1",
        decision="rejected",
        rejection_reason="Manual review required.",
        clear_patch=True,
    )

    payload = output_path.read_text(encoding="utf-8")

    assert '"decision": "rejected"' in payload
    assert '"rejection_reason": "Manual review required."' in payload
    assert '"patch"' not in payload
