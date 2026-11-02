import json

import pytest

from zeroone_ops.models.review_overview import ReviewOverviewEnvelope
from zeroone_ops.services.review.publish import review_overview_codec as codec
from zeroone_ops.services.review.publish.review_overview_renderer import render_overview


def test_default_three_finding_retention_fits_encoded_budget_losslessly(
    overview_envelope: ReviewOverviewEnvelope,
) -> None:
    before = overview_envelope.model_dump(mode="json")
    body = codec.encode_overview(overview_envelope)

    assert codec.MAX_OVERVIEW_BYTES == 60_000
    assert len(body.encode("utf-8")) < codec.MAX_OVERVIEW_BYTES
    assert len(body.encode("utf-8")) > len(body)
    assert codec.validate_overview_payload(body) == body
    assert codec.decode_overview(body) == overview_envelope
    assert overview_envelope.model_dump(mode="json") == before
    assert overview_envelope.complete_passes[0].projection_pending
    assert all(
        len(snapshot.inline_decisions) == 3 for snapshot in overview_envelope.complete_passes
    )


@pytest.mark.parametrize("full_body", [False, True])
def test_comment_delimiters_and_unicode_escape_losslessly(
    overview_envelope: ReviewOverviewEnvelope,
    full_body: bool,
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    hostile_text = (
        "<!-- nested --> <script>& Caf\u00e9 \u6771\u4eac \U0001f512 Cafe\u0301 "
        "\\u003c literal escape\n"
        f"{codec.OVERVIEW_START}{{}}{codec.OVERVIEW_END}"
    )
    payload["complete_passes"][0]["artifact"]["findings"][0]["evidence"] = hostile_text
    payload["execution_notice"] = hostile_text
    envelope = ReviewOverviewEnvelope.model_validate(payload)

    body = render_overview(envelope) if full_body else codec.encode_overview(envelope)
    encoded_payload = body.split(codec.OVERVIEW_START)[1].removesuffix(codec.OVERVIEW_END)

    assert "<" not in encoded_payload
    assert ">" not in encoded_payload
    assert "&" not in encoded_payload
    assert body.count(codec.OVERVIEW_START) == body.count(codec.OVERVIEW_END) == 1
    assert codec.decode_overview(body) == envelope
    assert envelope.complete_passes[0].artifact.findings[0].evidence == hostile_text


@pytest.mark.parametrize(
    "platform,repository_id,request_number",
    [
        ("github", "acme/shop", 17),
        ("gitlab", "284", 39),
    ],
)
def test_codec_preserves_exact_request_scope(
    overview_envelope: ReviewOverviewEnvelope,
    platform: str,
    repository_id: str,
    request_number: int,
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    payload.update(
        platform=platform, repository_id=repository_id, change_request_number=request_number
    )
    envelope = ReviewOverviewEnvelope.model_validate(payload)

    assert codec.decode_overview(codec.encode_overview(envelope)) == envelope


@pytest.mark.parametrize("with_inline_links", [True, False])
def test_real_rendered_body_fits_budget_and_preserves_complete_authority(
    overview_envelope: ReviewOverviewEnvelope,
    with_inline_links: bool,
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    if not with_inline_links:
        for snapshot in payload["complete_passes"]:
            for finding in snapshot["artifact"]["findings"]:
                finding["inline_comment"]["comment_url"] = None
    envelope = ReviewOverviewEnvelope.model_validate(payload)
    before = envelope.model_dump(mode="json")

    body = render_overview(envelope)

    assert len(body.encode("utf-8")) < 60_000
    assert len(body.encode("utf-8")) > len(codec.encode_overview(envelope).encode("utf-8"))
    assert codec.decode_overview(body) == envelope
    assert envelope.model_dump(mode="json") == before
    assert len(envelope.complete_passes) == 2
    assert len(envelope.history) == 5
    assert envelope.complete_passes[0].projection_pending
    assert envelope.complete_passes[0].projection_warning is not None


def test_full_body_gate_counts_visible_text_and_does_not_mutate_authority(
    overview_envelope: ReviewOverviewEnvelope,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_body = render_overview(overview_envelope)
    before = overview_envelope.model_dump(mode="json")
    full_byte_count = len(original_body.encode("utf-8"))
    monkeypatch.setattr(codec, "MAX_OVERVIEW_BYTES", full_byte_count)
    assert render_overview(overview_envelope) == original_body

    monkeypatch.setattr(codec, "MAX_OVERVIEW_BYTES", full_byte_count - 1)
    assert len(codec.encode_overview(overview_envelope).encode("utf-8")) < full_byte_count - 1
    with pytest.raises(codec.ReviewOverviewError, match="payload budget"):
        render_overview(overview_envelope)

    assert overview_envelope.model_dump(mode="json") == before
    monkeypatch.setattr(codec, "MAX_OVERVIEW_BYTES", 60_000)
    assert render_overview(overview_envelope) == original_body


def test_quality_disclaimer_is_a_footer_without_unconfigured_notice(
    overview_envelope: ReviewOverviewEnvelope,
) -> None:
    body = render_overview(overview_envelope)
    disclaimer = "AI review does not replace CI checks or merge approval."

    assert "Quality evidence not configured" not in body
    assert body.count(disclaimer) == 1
    assert body.index("**Next action:**") < body.index("Recent review history")
    assert body.index("</details>") < body.index(disclaimer) < body.index(codec.OVERVIEW_START)
    assert codec.decode_overview(body) == overview_envelope


@pytest.mark.parametrize("known_count", [0, 1, 3])
def test_continuity_counts_do_not_classify_unknown_findings(
    overview_envelope: ReviewOverviewEnvelope, known_count: int
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    findings = payload["complete_passes"][0]["artifact"]["findings"]
    for index, finding in enumerate(findings):
        finding["continuity_status"] = "unresolved" if index < known_count else None

    body = render_overview(ReviewOverviewEnvelope.model_validate(payload))
    count_line = next(line for line in body.splitlines() if line.startswith("**Active findings:**"))

    if known_count == 0:
        assert count_line == "**Active findings:** 3"
    else:
        assert f"0 new, {known_count} unresolved" in count_line
        if known_count < 3:
            assert f"{3 - known_count} without continuity classification" in count_line


def test_utf8_budget_rejects_without_mutating_or_truncating_evidence(
    overview_envelope: ReviewOverviewEnvelope,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = codec.encode_overview(overview_envelope)
    before = overview_envelope.model_dump(mode="json")
    byte_count = len(body.encode("utf-8"))
    # Move the gate, not the evidence: this is the same realistic review at its byte boundary.
    monkeypatch.setattr(codec, "MAX_OVERVIEW_BYTES", byte_count)
    assert codec.validate_overview_payload(body) is body
    assert codec.decode_overview(body) == overview_envelope

    monkeypatch.setattr(codec, "MAX_OVERVIEW_BYTES", byte_count - 1)
    assert len(body) < codec.MAX_OVERVIEW_BYTES
    with pytest.raises(codec.ReviewOverviewError, match="payload budget"):
        codec.validate_overview_payload(body)
    with pytest.raises(codec.ReviewOverviewError, match="payload budget"):
        codec.decode_overview(body)

    assert overview_envelope.model_dump(mode="json") == before
    assert codec.encode_overview(overview_envelope) == body


@pytest.mark.parametrize("body", [None, "", "A human review without managed authority."])
def test_unmanaged_body_has_no_overview(body: str | None) -> None:
    assert codec.decode_overview(body) is None


@pytest.mark.parametrize(
    "corruption",
    ["duplicate", "missing_start", "missing_end", "reversed", "invalid_json", "invalid_schema"],
)
def test_rejects_malformed_or_ambiguous_authority(
    overview_envelope: ReviewOverviewEnvelope,
    corruption: str,
) -> None:
    body = codec.encode_overview(overview_envelope)
    if corruption == "duplicate":
        body += body
    elif corruption == "missing_start":
        body = body.removeprefix(codec.OVERVIEW_START)
    elif corruption == "missing_end":
        body = body.removesuffix(codec.OVERVIEW_END)
    elif corruption == "reversed":
        body = codec.OVERVIEW_END + codec.OVERVIEW_START
    elif corruption == "invalid_json":
        body = f"{codec.OVERVIEW_START}{{broken{codec.OVERVIEW_END}"
    else:
        payload = overview_envelope.model_dump(mode="json")
        payload["schema_version"] = "zeroone/review-overview/v99"
        body = f"{codec.OVERVIEW_START}{json.dumps(payload)}{codec.OVERVIEW_END}"

    with pytest.raises(codec.ReviewOverviewError):
        codec.decode_overview(body)
