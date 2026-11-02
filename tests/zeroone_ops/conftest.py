from datetime import UTC, datetime

import pytest

from zeroone_ops.models.review import (
    ChangeRequestDiffRefs,
    PriorReviewInlineComment,
    PublishableReviewArtifact,
    PublishableReviewFinding,
)
from zeroone_ops.models.review_overview import ReviewOverviewEnvelope, ReviewOverviewPass
from zeroone_ops.models.state import ReviewInlineCommentDecision


@pytest.fixture
def overview_envelope() -> ReviewOverviewEnvelope:
    """Model a default three-finding review with full provider retention and repair evidence."""
    concerns = [
        (
            "src/orders/repository.py",
            "OrderRepository.reserve",
            84,
            "transaction_boundary",
            "Commit inventory and reservation atomically",
            "`decrement_stock(sku, quantity)` commits before `insert_reservation(order_id)`; "
            "the exception handler rolls back only the second transaction.",
            "When reservation insertion fails on the unique order constraint, stock remains "
            "decremented even though checkout returns an error. Retrying the same order can "
            "consume inventory twice and prevent another customer from buying available stock.",
            "Run both writes in the same transaction and add a regression test that injects "
            "an insertion failure, then asserts neither stock nor reservations changed.",
        ),
        (
            "src/api/export.py",
            "download_export",
            126,
            "authorization",
            "Scope export lookup to the authenticated tenant",
            "The changed query uses `exports.get(export_id)` and returns its signed download "
            "URL without comparing `export.tenant_id` with the authenticated session.",
            "A user who obtains another tenant's export identifier can download its customer "
            "records. The route's authentication dependency establishes identity but does not "
            "authorize access to the selected export, so the new lookup bypasses isolation.",
            "Filter by the session tenant in the repository query and return not found for "
            "cross-tenant identifiers. Cover both an authorized download and a foreign export.",
        ),
        (
            "src/search/normalization.py",
            "normalize_query",
            47,
            "unicode_normalization",
            "Normalize accented queries before generating cache keys",
            "The cache key now uses `query.lower()` while the search index continues to apply "
            "Unicode NFC normalization. Caf\u00e9 and Cafe\u0301 therefore select "
            "different cache entries.",
            "Canonically equivalent customer queries no longer share invalidation keys. After "
            "an indexed document changes, the decomposed spelling can keep serving stale "
            "results while the composed spelling refreshes, including for Japanese "
            "\u6771\u4eac queries.",
            "Apply the index's normalization before key construction and test composed and "
            "decomposed accents against the same cache entry and invalidation operation.",
        ),
    ]
    passes = []
    for sequence in range(5, 0, -1):
        findings = []
        decisions = []
        for index, (path, symbol, line, kind, title, evidence, impact, follow_up) in enumerate(
            concerns, start=1
        ):
            identity = f"{path}::{kind}"
            comment_id = str(8100 + sequence * 10 + index)
            findings.append(
                PublishableReviewFinding(
                    severity="high" if index < 3 else "medium",
                    file_path=path,
                    symbol=symbol,
                    line_start=line,
                    line_end=line + 3,
                    issue_kind=kind,
                    region_hint=f"{symbol}:changed-branch",
                    title=title,
                    evidence=evidence,
                    explanation=impact,
                    suggested_follow_up=follow_up,
                    stable_identity=identity,
                    legacy_identity=f"{path}::{title}",
                    continuity_status="new" if sequence == 4 else "unresolved",
                    inline_comment=PriorReviewInlineComment(
                        comment_id=comment_id,
                        comment_url=f"https://github.com/acme/shop/pull/17#discussion_r{comment_id}",
                        status="published",
                        anchor_file_path=path,
                        anchor_line_start=line,
                        anchor_line_end=line + 3,
                    ),
                )
            )
            decisions.append(
                ReviewInlineCommentDecision(
                    finding_identity=identity,
                    severity=findings[-1].severity,
                    file_path=path,
                    line_start=line,
                    line_end=line + 3,
                    region_hint=f"{symbol}:changed-branch",
                    inline_comments_enabled=True,
                    location_trust="trusted",
                    existing_inline_comment_found=True,
                    anchor_reuse_decision="reuse",
                    anchor_reuse_reason="Existing discussion still anchors the unchanged defect.",
                    authoritative_note_id=777,
                    existing_comment_id=comment_id,
                )
            )
        passes.append(
            ReviewOverviewPass(
                pass_id=f"review-pass-{sequence}",
                run_id=f"github-actions-{12000 + sequence}",
                head_sha=f"{sequence:040x}",
                sequence=sequence,
                completed_at=datetime(2026, 11, sequence, 12, 30, tzinfo=UTC),
                diff_refs=ChangeRequestDiffRefs(
                    base_sha="a" * 40,
                    start_sha="b" * 40,
                    head_sha=f"{sequence:040x}",
                ),
                artifact=PublishableReviewArtifact(
                    classification="findings_present",
                    summary="Three actionable concerns remain: atomic reservations, tenant-scoped "
                    "exports, and consistent Unicode cache invalidation. Each is grounded in the "
                    "changed implementation and needs a targeted regression test.",
                    review_confidence=0.91,
                    review_confidence_reason="The changed branches and their callers establish the "
                    "failure paths; repository tests do not cover the identified edge cases.",
                    findings=findings,
                    advisory_notes=["Keep authorization at the query boundary, not in rendering."],
                    follow_up_lines=[
                        "Reservation and export concerns remain open from the prior pass."
                    ],
                ),
                inline_decisions=decisions,
                projection_pending=sequence == 5,
                projection_warning=(
                    "Issue projection timed out; retry without repeating inline comments."
                )
                if sequence == 5
                else None,
                projection_reference="https://github.com/acme/shop/issues/42",
                workflow_url=f"https://github.com/acme/shop/actions/runs/{12000 + sequence}",
            )
        )
    return ReviewOverviewEnvelope(
        platform="github",
        repository_id="acme/shop",
        change_request_number=17,
        complete_passes=passes[:2],
        history=[snapshot.summary() for snapshot in passes],
        execution_notice=(
            "Projection repair pending; completed review evidence remains authoritative."
        ),
    )
