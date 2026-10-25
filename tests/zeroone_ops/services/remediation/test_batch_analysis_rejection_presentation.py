"""Keep batch stop explanations bounded, literal, and separate from authority."""

import pytest
from test_batch_execution_scope_service import attempted_work_item

from zeroone_ops.models.batch_execution import BatchAnalysisRejection, BatchRejectedMember
from zeroone_ops.services.remediation.batch_analysis_rejection_presentation import (
    build_batch_analysis_rejection_view,
    format_batch_analysis_stop,
    render_batch_analysis_rejection_lines,
    render_batch_analysis_stop_lines,
)


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("manual_classification", "Model requested manual handling."),
        ("missing_coverage", "Model response did not account for the batch findings."),
        ("invalid_coverage", "Model response contained inconsistent batch accounting."),
        ("unaddressable_members", "Model could not address every targeted finding."),
    ],
)
def test_stop_categories_resolve_recorded_locations_without_mutation(reason, expected):
    state = attempted_work_item()
    rejection = BatchAnalysisRejection(
        reason=reason,
        members=(
            BatchRejectedMember(finding_reference="member-1", reason="Needs local reasoning."),
        ),
    )
    before = state.model_dump_json(), rejection.model_dump_json()
    view = build_batch_analysis_rejection_view(rejection, attempt=state.batch_attempt)

    assert view.summary == expected
    assert view.members[0].recorded_location == "src/service.py:2; rule: F401"
    assert "No edit was generated or published by this attempt." in format_batch_analysis_stop(view)
    assert (state.model_dump_json(), rejection.model_dump_json()) == before


@pytest.mark.parametrize("reference", ["unknown", "member-", "x" * 297 + "..."])
def test_unresolved_references_never_infer_a_line(reference):
    rejection = BatchAnalysisRejection(
        reason="manual_classification",
        members=(BatchRejectedMember(finding_reference=reference, reason="Review manually."),),
    )
    view = build_batch_analysis_rejection_view(
        rejection,
        attempt=attempted_work_item().batch_attempt,
        file_path="src/service.py",
        rule_id="F401",
    )
    assert view.members[0].recorded_location == "src/service.py (line unavailable); rule: F401"


def test_preview_and_details_disclose_omissions_and_escape_model_text():
    rejection = BatchAnalysisRejection(
        reason="unaddressable_members",
        members=tuple(
            BatchRejectedMember(
                finding_reference=f"ref-{i}", reason="[click](url) <b>\n" + "é" * 560
            )
            for i in range(10)
        ),
        omitted_member_count=4,
    )
    view = build_batch_analysis_rejection_view(rejection)
    preview = "\n".join(render_batch_analysis_stop_lines(view))
    details = "\n".join(render_batch_analysis_rejection_lines(view))
    plain = format_batch_analysis_stop(view)

    assert preview.count("Recorded location:") == 3
    assert "11 more affected findings" in preview
    assert "11 more affected findings" in plain
    assert "é" * 301 not in preview
    assert details.count("Recorded location:") == 10
    assert "4 more affected findings" in details
    assert "[click](url)" not in details
    assert "<b>" not in details
    assert "&lt;b&gt;" in details
    assert details.index("<summary>Technical finding references") < details.index("Member: ref-0")


def test_plain_text_removes_terminal_controls_and_newlines_from_evidence():
    rejection = BatchAnalysisRejection(
        reason="manual_classification",
        members=(BatchRejectedMember(finding_reference="a", reason="Stop\n\x1bunsafe\x00text"),),
    )
    message = format_batch_analysis_stop(build_batch_analysis_rejection_view(rejection))
    assert "Explanation: Stop unsafetext" in message
    assert "\x1b" not in message
    assert "\x00" not in message


@pytest.mark.parametrize("scenario", ["missing_attempt", "ambiguous", "missing_line", "truncated"])
def test_locations_require_unique_untruncated_recorded_evidence(scenario):
    attempt = attempted_work_item().batch_attempt
    member = attempt.members[0]
    reference = member.finding_id
    if scenario == "missing_attempt":
        attempt = None
    elif scenario == "ambiguous":
        attempt = attempt.model_copy(update={"members": (member, member)})
    elif scenario == "missing_line":
        member = member.model_copy(update={"line_start": None})
        attempt = attempt.model_copy(update={"members": (member,)})
    else:
        reference = "x" * 297 + "..."
        member = member.model_copy(update={"finding_id": reference})
        attempt = attempt.model_copy(update={"members": (member,)})
    rejection = BatchAnalysisRejection(
        reason="manual_classification",
        members=(BatchRejectedMember(finding_reference=reference, reason="Review manually."),),
    )
    view = build_batch_analysis_rejection_view(rejection, attempt=attempt)
    assert "line unavailable" in view.members[0].recorded_location
