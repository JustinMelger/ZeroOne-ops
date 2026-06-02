from pathlib import Path

from zeroone_ops.models.analysis import AnalysisClassification, IssueAnalysis, PatchProposal
from zeroone_ops.utils.solution_artifacts import write_solution_artifact


def test_write_solution_artifact_persists_analysis_and_patch(tmp_path: Path) -> None:
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

    write_solution_artifact(output_path, issue_key="AX1", analysis=analysis)
    write_solution_artifact(output_path, issue_key="AX1", patch=patch)

    payload = output_path.read_text(encoding="utf-8")

    assert output_path.exists()
    assert '"issue_key": "AX1"' in payload
    assert '"summary": "Summary"' in payload
    assert '"mr_title": "fix: update service"' in payload


def test_write_solution_artifact_can_record_rejection_and_clear_patch(tmp_path: Path) -> None:
    output_path = tmp_path / "artifacts" / "openai-solution.json"
    patch = PatchProposal(
        issue_key="AX1",
        files_touched=["src/service.py"],
        unified_diff="diff --git a/src/service.py b/src/service.py\n",
        commit_message="fix(sonar): update service [AX1]",
        mr_title="fix: update service",
        mr_description="summary",
    )

    write_solution_artifact(output_path, issue_key="AX1", patch=patch)
    write_solution_artifact(
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
