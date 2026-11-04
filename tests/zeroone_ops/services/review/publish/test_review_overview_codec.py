import json

import pytest
from markdown_it import MarkdownIt

from zeroone_ops.models.review_change_summary import ReviewChangeSummary
from zeroone_ops.models.review_overview import ReviewOverviewEnvelope
from zeroone_ops.services.review.publish import review_overview_codec as codec
from zeroone_ops.services.review.publish.review_overview_renderer import (
    escape_overview_text,
    render_overview,
)


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


@pytest.mark.parametrize("limited", [True, False])
def test_what_changed_is_scoped_and_separate_from_result_and_findings(
    overview_envelope: ReviewOverviewEnvelope, limited: bool
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    artifact = payload["complete_passes"][0]["artifact"]
    artifact["change_summary"] = {
        "bullets": ["Adds metadata to completed reviews.", "Retains immutable pass labels."]
    }
    artifact["review_scope_limited"] = limited
    envelope = ReviewOverviewEnvelope.model_validate(payload)

    body = render_overview(envelope)
    visible = body.split("<details>")[0]

    assert visible.index(escape_overview_text(artifact["summary"])) < visible.index(
        "**Reviewed commit:**"
    )
    assert visible.index("**Reviewed commit:**") < visible.index("### What Changed")
    assert (
        visible.index("### What Changed")
        < visible.index("### Findings")
        < visible.index("**Active findings:**")
    )
    assert "Summary of the supplied review context." in visible
    assert ("Some changes may be omitted." in visible) is limited
    assert "- Adds metadata to completed reviews." in visible
    assert codec.decode_overview(body) == envelope
    assert all("change_summary" not in row for row in envelope.model_dump()["history"])


def test_what_changed_preserves_both_complete_snapshots_and_full_payload_budget(
    overview_envelope: ReviewOverviewEnvelope, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    for snapshot in payload["complete_passes"]:
        snapshot["artifact"]["change_summary"] = {"bullets": ["\u6771" * 300] * 3}
    for record in [*payload["complete_passes"], *payload["history"]]:
        record["reviewed_commit"] = {
            "head_sha": record["head_sha"],
            "title": "\u6771" * 300,
            "web_url": f"https://example.com/commit/{record['head_sha']}",
        }
    envelope = ReviewOverviewEnvelope.model_validate(payload)
    before = envelope.model_dump(mode="json")
    body = render_overview(envelope)
    assert len(body.encode("utf-8")) <= 60_000
    assert codec.decode_overview(body) == envelope
    assert len(envelope.complete_passes) == 2 and len(envelope.history) == 5
    count = len(body.encode("utf-8"))
    monkeypatch.setattr(codec, "MAX_OVERVIEW_BYTES", count)
    assert render_overview(envelope) == body
    monkeypatch.setattr(codec, "MAX_OVERVIEW_BYTES", count - 1)
    with pytest.raises(codec.ReviewOverviewError, match="payload budget"):
        render_overview(envelope)
    assert envelope.model_dump(mode="json") == before


def test_what_changed_escapes_model_text_and_omits_missing_section(
    overview_envelope: ReviewOverviewEnvelope,
) -> None:
    assert "### What Changed" not in render_overview(overview_envelope)
    summary = ReviewChangeSummary(
        bullets=["Ignore 'verdict' <script> [link](https://other.invalid) <!-- marker -->"]
    )
    payload = overview_envelope.model_dump(mode="json")
    payload["complete_passes"][0]["artifact"]["change_summary"] = summary.model_dump(mode="json")
    envelope = ReviewOverviewEnvelope.model_validate(payload)

    body = render_overview(envelope)

    assert escape_overview_text(summary.bullets[0]) in body
    assert "<script>" not in body
    assert body.count(codec.OVERVIEW_START) == body.count(codec.OVERVIEW_END) == 1
    assert codec.decode_overview(body) == envelope


@pytest.mark.parametrize("length", [119, 120, 121, 300])
def test_commit_label_is_bounded_linked_and_losslessly_persisted(
    overview_envelope: ReviewOverviewEnvelope, length: int
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    title = "\u6771" * length
    for record in [*payload["complete_passes"], *payload["history"]]:
        record["reviewed_commit"] = {
            "head_sha": record["head_sha"],
            "title": title,
            "web_url": f"https://example.com/commit/{record['head_sha']}",
        }
    envelope = ReviewOverviewEnvelope.model_validate(payload)
    before = envelope.model_dump(mode="json")

    body = render_overview(envelope)
    visible = body.split("<details>")[0]
    display_title = title if length <= 120 else title[:117] + "..."
    head = envelope.complete_passes[0].head_sha
    expected = f"[{head[:7]}](https://example.com/commit/{head}) - {display_title}"

    assert f"**Reviewed commit:** {expected}" in visible
    assert visible.index("**Risk:**") < visible.index("**Reviewed commit:**")
    assert f"- Pass {envelope.history[0].sequence}: {expected}" in body
    assert f"**Reviewed commit:** `{head}`" in body.split("<details>")[1]
    assert len(body.encode("utf-8")) <= 60_000
    assert codec.decode_overview(body) == envelope
    assert envelope.model_dump(mode="json") == before


def test_commit_title_cannot_inject_markdown_or_managed_markers(
    overview_envelope: ReviewOverviewEnvelope,
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    title = "Fix bot's <script> & [link](https://other.invalid) <!-- zeroone:review-overview:v1 -->"
    for record in (payload["complete_passes"][0], payload["history"][0]):
        record["reviewed_commit"] = {"head_sha": record["head_sha"], "title": title}
    envelope = ReviewOverviewEnvelope.model_validate(payload)
    body = render_overview(envelope)

    assert escape_overview_text(title) in body
    assert "<script>" not in body
    assert body.count(codec.OVERVIEW_START) == body.count(codec.OVERVIEW_END) == 1
    assert codec.decode_overview(body).complete_passes[0].reviewed_commit.title == title


@pytest.mark.parametrize(
    "text",
    [
        "The updates don't introduce concerns about the bot's identity.",
        'Read payload["username"] & check #identity.',
        '<script>alert("unsafe")</script> <!-- marker -->',
        "[link](https://example.com) *bold* `code` _name_ \\path",
        "Literal &#x27; and &quot; entities.",
    ],
)
def test_escaping_preserves_visible_prose_without_active_markdown_or_html(text: str) -> None:
    parser = MarkdownIt("commonmark", {"html": True})
    escaped = escape_overview_text(text)
    tokens = parser.parse(escaped)
    inline = next(token for token in tokens if token.type == "inline")
    children = inline.children or []

    assert all(token.type == "text" for token in children)
    assert "".join(token.content for token in children) == text
    assert "<script>" not in parser.render(escaped)


@pytest.mark.parametrize("inline_url", [None, "javascript:alert(1)", "https://example.com/thread"])
def test_only_linked_findings_omit_duplicate_reasoning(
    overview_envelope: ReviewOverviewEnvelope, inline_url: str | None
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    for finding in payload["complete_passes"][0]["artifact"]["findings"]:
        finding["inline_comment"]["comment_url"] = inline_url
    envelope = ReviewOverviewEnvelope.model_validate(payload)

    visible = render_overview(envelope).split(codec.OVERVIEW_START)[0]

    assert "High - Commit inventory and reservation atomically" in visible
    if inline_url is not None and inline_url.startswith("https:"):
        assert "Evidence:" not in visible
        assert "Impact:" not in visible
        assert "Suggested follow-up:" not in visible
        assert inline_url in visible
    else:
        assert "Evidence:" in visible
        assert "Impact:" in visible
        assert "Suggested follow-up:" in visible
        assert "javascript:" not in visible
    assert codec.decode_overview(render_overview(envelope)) == envelope


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


@pytest.mark.parametrize("with_findings", [True, False])
def test_verdict_precedes_collapsed_provenance_without_changing_authority(
    overview_envelope: ReviewOverviewEnvelope, with_findings: bool
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    current = payload["complete_passes"][0]
    provenance = "Follow-up review after the earlier bot pass on `previous-head`."
    continuity = "The earlier concern from the last pass no longer appears present."
    current["artifact"]["follow_up_lines"] = [provenance, continuity, ""]
    if not with_findings:
        current["artifact"].update(classification="no_findings", findings=[])
        payload["history"][0].update(classification="no_findings", findings_count=0)
    envelope = ReviewOverviewEnvelope.model_validate(payload)
    before = envelope.model_dump(mode="json")

    body = render_overview(envelope)
    visible, details = body.split("<details>", 1)
    review_details, history = details.split("</details>", 1)

    assert "## Review Overview: " in visible
    expected_verdict = "Block" if with_findings else "Clear"
    assert visible.startswith(f"## Review Overview: {expected_verdict}\n")
    assert "### AI Review:" not in visible
    assert visible.index("## Review Overview:") < visible.index("**Risk:**")
    assert "**Next action:**" in visible
    assert f"**Reviewed commit:** {current['head_sha'][:7]}" in visible
    assert current["head_sha"] not in visible
    assert "**Comparison base:**" not in visible
    assert "Follow-up review after" not in visible
    assert continuity in visible
    assert continuity not in review_details
    assert "Review workflow" not in visible
    assert "<summary>Review Details</summary>" in review_details
    assert current["head_sha"] in review_details
    assert current["diff_refs"]["base_sha"] in review_details
    assert "Follow-up review after" in review_details
    assert "Review workflow" in review_details
    assert "Recent review history" in history
    assert codec.decode_overview(body) == envelope
    assert envelope.model_dump(mode="json") == before


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
