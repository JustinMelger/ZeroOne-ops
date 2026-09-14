from pathlib import Path

from zeroone_ops.models.analysis import (
    AnalysisClassification,
    IssueAnalysis,
    PatchProposal,
    StructuredEditProposal,
    TextEdit,
)
from zeroone_ops.services.remediation.solution_artifact_service import (
    SolutionArtifactService,
)


def build_analysis() -> IssueAnalysis:
    return IssueAnalysis(
        issue_key="AX1",
        classification=AnalysisClassification.AUTO_FIXABLE,
        summary="Summary",
        risk_notes=[],
        target_files=["src/service.py"],
        proposed_strategy="Make the minimal fix.",
        semantic_safety={
            "current_behavior": "Current local behavior.",
            "intended_behavior": "Minimal correction.",
            "preservation_evidence": ["One-file scope."],
        },
    )


def build_patch() -> PatchProposal:
    return PatchProposal(
        issue_key="AX1",
        files_touched=["src/service.py"],
        unified_diff="diff --git a/src/service.py b/src/service.py\n",
        commit_message="fix(sonar): update service [AX1]",
        change_request_title="fix: update service",
        change_request_description="summary",
    )


def build_structured_edit() -> StructuredEditProposal:
    return StructuredEditProposal(
        issue_key="AX1",
        edits=[
            TextEdit(
                file_path="src/service.py",
                search_text="value = 1",
                replace_text="value = 2",
                line_hint=1,
            )
        ],
        commit_message="fix(sonar): update service [AX1]",
        change_request_title="fix: update service",
        change_request_description="summary",
    )


def test_solution_artifact_service_writes_analysis_structured_edit_and_patch(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "artifacts" / "openai-solution.json"
    service = SolutionArtifactService(output_path)

    service.write_analysis(issue_key="AX1", analysis=build_analysis())
    service.write_structured_edit(issue_key="AX1", structured_edit=build_structured_edit())
    service.write_patch(issue_key="AX1", patch=build_patch())

    payload = output_path.read_text(encoding="utf-8")

    assert '"issue_key": "AX1"' in payload
    assert '"summary": "Summary"' in payload
    assert '"structured_edit"' in payload
    assert '"search_text": "value = 1"' in payload
    assert '"change_request_title": "fix: update service"' in payload


def test_solution_artifact_service_skips_writes_when_disabled(tmp_path: Path) -> None:
    service = SolutionArtifactService(None)

    service.write_analysis(issue_key="AX1", analysis=build_analysis())
    service.write_structured_edit(issue_key="AX1", structured_edit=build_structured_edit())
    service.write_patch(issue_key="AX1", patch=build_patch())
    service.write_manual_rejection(issue_key="AX1")

    assert not (tmp_path / "artifacts" / "openai-solution.json").exists()
