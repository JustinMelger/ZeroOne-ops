"""Bound rejected analysis evidence without weakening complete-scope checks."""

import pytest
from test_batch_analysis_execution import analysis
from test_batch_execution_scope_service import attempted_work_item

from zeroone_ops.models.analysis import AnalysisClassification
from zeroone_ops.models.batch_execution import (
    BatchAnalysisCoverage,
    BatchAttemptEvidence,
    BatchUnaddressableMember,
)
from zeroone_ops.services.remediation.batch_analysis_rejection_presentation import (
    build_batch_analysis_rejection_view,
    render_batch_analysis_rejection_lines,
)
from zeroone_ops.services.remediation.batch_execution_checks import (
    BatchAnalysisRejected,
    accept_batch_analysis,
)


@pytest.mark.parametrize("manual", [False, True])
def test_rejection_has_bounded_display_references_reasons_and_omitted_count(manual):
    initial = attempted_work_item().batch_attempt
    members = tuple(
        initial.members[0].model_copy(update={"finding_id": f"member-{i}-" + "x" * 400})
        for i in range(12)
    )
    attempt = BatchAttemptEvidence.model_validate(initial.model_dump() | {"members": members})
    coverage = BatchAnalysisCoverage(
        addressable_ids=tuple(member.finding_id for member in members) if manual else (),
        unaddressable=()
        if manual
        else tuple(
            BatchUnaddressableMember(finding_id=member.finding_id, reason="Needs another file")
            for member in members
        ),
    )
    response = analysis(
        coverage,
        classification=AnalysisClassification.MANUAL
        if manual
        else AnalysisClassification.AUTO_FIXABLE,
    ).model_copy(update={"summary": "s" * 900})

    with pytest.raises(BatchAnalysisRejected) as caught:
        accept_batch_analysis(attempt, response)

    rejection = caught.value.rejection
    assert len(rejection.members) == 10
    assert rejection.omitted_member_count == 2
    assert all(len(member.finding_reference) == 300 for member in rejection.members)
    assert all(member.finding_reference.endswith("...") for member in rejection.members)
    assert all(len(member.reason) <= 600 for member in rejection.members)
    if manual:
        assert all(member.reason.endswith("...") for member in rejection.members)
    view = build_batch_analysis_rejection_view(rejection, attempt=attempt)
    assert "2 more affected findings" in "\n".join(render_batch_analysis_rejection_lines(view))
    assert all("line unavailable" in member.recorded_location for member in view.members)
    assert attempt.coverage is None


def test_missing_attempt_returns_no_manufactured_member_references():
    with pytest.raises(BatchAnalysisRejected) as caught:
        accept_batch_analysis(None, analysis())
    assert caught.value.rejection.reason == "missing_coverage"
    assert caught.value.rejection.members == ()
