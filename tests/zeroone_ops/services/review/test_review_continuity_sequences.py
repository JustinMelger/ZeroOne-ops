from zeroone_ops.models.review import (
    MergeRequestReviewContext,
    PriorReviewContext,
    PriorReviewFinding,
    PriorReviewPass,
    ReviewFileContext,
    ReviewFinding,
    ReviewResult,
)
from zeroone_ops.services.review.review_overlap_packet_builder import (
    OverlapPacketBuilder,
)
from zeroone_ops.services.review.review_overlap_reconciliation import (
    OverlapReconciliationService,
)
from zeroone_ops.utils.review_finding_identity import (
    build_legacy_review_finding_identity,
    build_review_finding_identity,
)


def _build_context(
    *,
    head_sha: str,
    prior_pass: PriorReviewPass | None = None,
) -> MergeRequestReviewContext:
    return MergeRequestReviewContext(
        mr_iid=120,
        title="test: continuity sequence",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/120",
        head_sha=head_sha,
        changed_files=[
            ReviewFileContext(
                file_path="bnl_app/functions/vehicle_functions.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="raise ValueError",
                full_file_included=True,
                truncated=False,
            )
        ],
        prior_review_context=(
            None
            if prior_pass is None
            else PriorReviewContext(
                merge_request_iid=120,
                passes=[prior_pass],
            )
        ),
    )


def _build_prior_pass(reviewed_head_sha: str, findings: list[ReviewFinding]) -> PriorReviewPass:
    return PriorReviewPass(
        reviewed_head_sha=reviewed_head_sha,
        classification="findings_present",
        findings_count=len(findings),
        summary=f"{len(findings)} earlier concerns still need attention.",
        findings=[
            PriorReviewFinding(
                identity=build_review_finding_identity(finding),
                legacy_identity=build_legacy_review_finding_identity(finding),
                summary=f"{finding.file_path}: {finding.title}",
                severity=finding.severity,
                symbol=finding.symbol,
                issue_kind=finding.issue_kind,
                region_hint=finding.region_hint,
            )
            for finding in findings
        ],
    )


def _reconcile_sequence(
    *,
    head_sha: str,
    prior_pass: PriorReviewPass | None,
    findings: list[ReviewFinding],
) -> tuple[list[str], list[str], list[str], list[list[int]]]:
    context = _build_context(head_sha=head_sha, prior_pass=prior_pass)
    review_result = ReviewResult(
        classification="findings_present" if findings else "no_findings",
        summary=f"{len(findings)} findings.",
        findings=findings,
    )
    packet = OverlapPacketBuilder().build(context=context, review_result=review_result)
    assert packet is not None
    result = OverlapReconciliationService().reconcile(packet=packet)

    still_unresolved = [
        packet.prior_findings[resolution.prior_finding_index].summary
        for resolution in result.resolutions
        if resolution.outcome == "still_unresolved" and resolution.prior_finding_index is not None
    ]
    new_in_this_pass = [
        packet.current_findings[resolution.current_finding_index].file_path
        + ": "
        + packet.current_findings[resolution.current_finding_index].title
        for resolution in result.resolutions
        if resolution.outcome == "new_in_this_pass" and resolution.current_finding_index is not None
    ]
    no_longer_present = [
        packet.prior_findings[resolution.prior_finding_index].summary
        for resolution in result.resolutions
        if resolution.outcome == "no_longer_present" and resolution.prior_finding_index is not None
    ]
    ambiguous = [
        resolution.related_prior_finding_indices
        for resolution in result.resolutions
        if resolution.outcome == "overlap_ambiguous"
    ]
    return still_unresolved, new_in_this_pass, no_longer_present, ambiguous


def _cylinder_finding() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="bnl_app/functions/vehicle_articles_functions.py",
        symbol="get_number_of_cylinders",
        issue_kind="unconditional_exception",
        region_hint="function-entry",
        title="Function now always raises instead of returning cylinder count",
        evidence="raise ValueError is inserted before any existing lookup logic.",
        explanation="Every caller now fails instead of receiving a cylinder count or None.",
        suggested_follow_up="Remove the unconditional raise and restore the lookup flow.",
    )


def _vehicle_details_finding() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="bnl_app/functions/vehicle_functions.py",
        symbol="get_vehicle_details_long",
        issue_kind="unconditional_exception",
        region_hint="function-entry",
        title="Unconditional ValueError breaks vehicle detail retrieval",
        evidence="raise ValueError is inserted before the first call in the helper.",
        explanation="The vehicle details path now fails immediately for every caller.",
        suggested_follow_up="Remove the unconditional exception and restore the helper body.",
    )


def _filter_fields_finding() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="bnl_app/functions/vehicle_functions.py",
        symbol="filter_fields",
        issue_kind="unconditional_exception",
        region_hint="function-entry",
        title="Shared field-filtering helper now throws for all callers",
        evidence="raise ValueError is inserted before the filtering logic.",
        explanation=(
            "Any caller of the shared helper now fails instead of receiving a filtered dict."
        ),
        suggested_follow_up="Remove the unconditional raise and restore the filtering path.",
    )


def _ordering_finding_original() -> ReviewFinding:
    return ReviewFinding(
        severity="medium",
        file_path="src/service.py",
        symbol="Service.run",
        issue_kind="ordering_regression",
        region_hint="return-order",
        title="Ordering regression",
        evidence="The diff removes explicit stable ordering before return.",
        explanation="Returned results can now come back in a different sequence.",
        suggested_follow_up="Restore deterministic ordering.",
    )


def _ordering_finding_wording_drift() -> ReviewFinding:
    return ReviewFinding(
        severity="medium",
        file_path="src/service.py",
        symbol="Service.run",
        issue_kind="ordering_regression",
        region_hint="return-order",
        title="Ordering logic now returns a different sequence",
        evidence="The diff removes the stable sort before returning results.",
        explanation="The returned order can now drift between runs.",
        suggested_follow_up="Restore deterministic ordering.",
    )


def _helper_a_finding() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/helpers.py",
        symbol="build_vehicle_payload",
        issue_kind="unconditional_exception",
        region_hint="function-entry",
        title="Payload helper now always raises",
        evidence="raise ValueError is inserted before any payload construction logic.",
        explanation="All callers now fail before the helper can build vehicle payloads.",
        suggested_follow_up="Remove the unconditional raise and restore the helper body.",
    )


def _helper_b_finding() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/helpers.py",
        symbol="build_grouped_vehicle_payload",
        issue_kind="unconditional_exception",
        region_hint="function-entry",
        title="Grouped payload helper now always raises",
        evidence="raise ValueError is inserted before any grouped payload logic.",
        explanation="Grouped payload callers now fail before any grouping work runs.",
        suggested_follow_up="Remove the unconditional raise and restore the helper body.",
    )


def _vehicle_details_finding_llm_variant_a() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="bnl_app/functions/vehicle_functions.py",
        symbol="get_vehicle_details_long",
        issue_kind="unconditional_exception",
        region_hint="function-entry",
        title="Vehicle details helper now always raises",
        evidence="raise ValueError is inserted before the first call in the helper.",
        explanation="The helper now raises before existing lookup logic can run.",
        suggested_follow_up="Remove the unconditional exception and restore the helper body.",
    )


def _vehicle_details_finding_llm_variant_b() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="bnl_app/functions/vehicle_functions.py",
        symbol="get_vehicle_details_long",
        issue_kind="unconditional_exception",
        region_hint="function-entry",
        title="Vehicle details path now always fails before lookup",
        evidence="raise ValueError is inserted before any existing lookup calls.",
        explanation="The vehicle details path now fails before lookup work begins.",
        suggested_follow_up="Remove the unconditional exception and restore the helper body.",
    )


def _vehicle_details_finding_without_structured_fields() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="bnl_app/functions/vehicle_functions.py",
        title="Vehicle details path now always fails before lookup",
        evidence="raise ValueError is inserted before any existing lookup calls.",
        explanation="The vehicle details path now fails before lookup work begins.",
        suggested_follow_up="Remove the unconditional exception and restore the helper body.",
    )


def _same_title_unstructured_file_a() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/alpha.py",
        title="Request path now always fails before lookup",
        evidence="raise ValueError is inserted before the first lookup call.",
        explanation="The request path now fails before lookup work begins.",
        suggested_follow_up="Remove the unconditional exception and restore the request path.",
    )


def _same_title_unstructured_file_b() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/beta.py",
        title="Request path now always fails before lookup",
        evidence="raise ValueError is inserted before the first lookup call.",
        explanation="The request path now fails before lookup work begins.",
        suggested_follow_up="Remove the unconditional exception and restore the request path.",
    )


def _ambiguous_prior_helper_a() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/helpers.py",
        title="Payload helper now always raises",
        evidence="raise ValueError is inserted before payload work.",
        explanation="Payload helper callers now fail immediately.",
        suggested_follow_up="Remove the unconditional exception.",
    )


def _ambiguous_prior_helper_b() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/helpers.py",
        title="Vehicle payload helper now always raises",
        evidence="raise ValueError is inserted before vehicle payload work.",
        explanation="Vehicle payload callers now fail immediately.",
        suggested_follow_up="Remove the unconditional exception.",
    )


def _ambiguous_current_helper() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/helpers.py",
        title="Vehicle payload helper now fails before processing",
        evidence="raise ValueError is inserted before payload processing.",
        explanation="Vehicle payload callers now fail before processing begins.",
        suggested_follow_up="Remove the unconditional exception.",
    )


def _cache_guard_finding_high() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/cache.py",
        symbol="build_cache_key",
        issue_kind="missing_guard",
        region_hint="input-validation",
        title="Cache key builder no longer guards missing tenant id",
        evidence="The diff removes the explicit tenant id guard before key building.",
        explanation="The helper can now build an invalid cache key for missing tenant input.",
        suggested_follow_up="Restore the tenant id guard.",
    )


def _cache_guard_finding_low_wording_drift() -> ReviewFinding:
    return ReviewFinding(
        severity="low",
        file_path="src/cache.py",
        symbol="build_cache_key",
        issue_kind="missing_guard",
        region_hint="input-validation",
        title="Cache key helper now skips tenant validation",
        evidence="The diff removes the explicit tenant id check before key building.",
        explanation="The helper can now emit an invalid cache key when tenant input is absent.",
        suggested_follow_up="Restore tenant validation before building the cache key.",
    )


def _vehicle_types_prior_finding() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="core/external_clients/vehicle_lookup_service.py",
        symbol="extract_banner_details / get_general_info_group_vi_version",
        issue_kind="deterministic_runtime_error",
        region_hint="Vehicle-based detail helpers",
        title="Vehicle-based detail helpers assume `vehicle.types` is non-empty and can crash",
        evidence="The helper reads `vehicle.types[0]` fields directly.",
        explanation="Valid empty-list inputs can raise `IndexError`.",
        suggested_follow_up="Guard the first type lookup or use empty defaults.",
    )


def _vehicle_types_current_wording_drift() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="core/external_clients/vehicle_lookup_service.py",
        symbol="extract_banner_details / get_general_info_group_vi_version",
        issue_kind="deterministic_runtime_error",
        region_hint="new Vehicle-based banner/general-info helpers",
        title=(
            "Vehicle-based detail helpers index `vehicle.types[0]` without checking "
            "for an empty list"
        ),
        evidence="The helper reads `vehicle.types[0].brand`, `logo`, and code directly.",
        explanation="Valid empty-list inputs can still raise `IndexError`.",
        suggested_follow_up="Guard the first type lookup or use empty defaults.",
    )


def _empty_types_prior_finding() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="bnl_app/functions/vehicle_functions.py",
        symbol="get_vehicle_details_long",
        issue_kind="runtime_error",
        region_hint="UK/ROI details name fallback",
        title="UK/ROI details name fallback can index empty types",
        evidence="The helper indexes the first type row directly.",
        explanation="An empty types list can still raise at runtime.",
        suggested_follow_up="Guard the first type lookup before building the name fallback.",
    )


def _empty_types_current_issue_kind_drift() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="bnl_app/functions/vehicle_functions.py",
        symbol="get_vehicle_details_long",
        issue_kind="deterministic_runtime_error",
        region_hint="UK/ROI details name fallback",
        title="UK/ROI details name fallback indexes an empty types list",
        evidence="The helper still indexes the first type row directly.",
        explanation="An empty types list can still raise on the same fallback path.",
        suggested_follow_up="Guard the first type lookup before building the name fallback.",
    )


def test_valueerror_sequence_tracks_still_unresolved_new_and_resolved_findings() -> None:
    pass1_findings = [_cylinder_finding()]

    pass2_still, pass2_new, pass2_resolved, pass2_ambiguous = _reconcile_sequence(
        head_sha="sha-pass-2",
        prior_pass=_build_prior_pass("sha-pass-1", pass1_findings),
        findings=[_cylinder_finding(), _vehicle_details_finding()],
    )
    assert pass2_still == [
        "bnl_app/functions/vehicle_articles_functions.py: "
        "Function now always raises instead of returning cylinder count"
    ]
    assert pass2_new == [
        "bnl_app/functions/vehicle_functions.py: "
        "Unconditional ValueError breaks vehicle detail retrieval"
    ]
    assert pass2_resolved == []
    assert pass2_ambiguous == []

    pass3_still, pass3_new, pass3_resolved, pass3_ambiguous = _reconcile_sequence(
        head_sha="sha-pass-3",
        prior_pass=_build_prior_pass(
            "sha-pass-2", [_cylinder_finding(), _vehicle_details_finding()]
        ),
        findings=[_cylinder_finding(), _vehicle_details_finding(), _filter_fields_finding()],
    )
    assert pass3_still == [
        "bnl_app/functions/vehicle_articles_functions.py: "
        "Function now always raises instead of returning cylinder count",
        "bnl_app/functions/vehicle_functions.py: "
        "Unconditional ValueError breaks vehicle detail retrieval",
    ]
    assert pass3_new == [
        "bnl_app/functions/vehicle_functions.py: "
        "Shared field-filtering helper now throws for all callers"
    ]
    assert pass3_resolved == []
    assert pass3_ambiguous == []

    pass4_still, pass4_new, pass4_resolved, pass4_ambiguous = _reconcile_sequence(
        head_sha="sha-pass-4",
        prior_pass=_build_prior_pass(
            "sha-pass-3",
            [_cylinder_finding(), _vehicle_details_finding(), _filter_fields_finding()],
        ),
        findings=[_cylinder_finding(), _vehicle_details_finding()],
    )
    assert pass4_still == [
        "bnl_app/functions/vehicle_articles_functions.py: "
        "Function now always raises instead of returning cylinder count",
        "bnl_app/functions/vehicle_functions.py: "
        "Unconditional ValueError breaks vehicle detail retrieval",
    ]
    assert pass4_new == []
    assert pass4_resolved == [
        "bnl_app/functions/vehicle_functions.py: "
        "Shared field-filtering helper now throws for all callers"
    ]
    assert pass4_ambiguous == []


def test_wording_drift_sequence_keeps_same_concern_still_unresolved() -> None:
    pass2_still, pass2_new, pass2_resolved, pass2_ambiguous = _reconcile_sequence(
        head_sha="ordering-pass-2",
        prior_pass=_build_prior_pass("ordering-pass-1", [_ordering_finding_original()]),
        findings=[_ordering_finding_wording_drift()],
    )
    assert pass2_still == ["src/service.py: Ordering regression"]
    assert pass2_new == []
    assert pass2_resolved == []
    assert pass2_ambiguous == []

    pass3_still, pass3_new, pass3_resolved, pass3_ambiguous = _reconcile_sequence(
        head_sha="ordering-pass-3",
        prior_pass=_build_prior_pass("ordering-pass-2", [_ordering_finding_wording_drift()]),
        findings=[_ordering_finding_original()],
    )
    assert pass3_still == ["src/service.py: Ordering logic now returns a different sequence"]
    assert pass3_new == []
    assert pass3_resolved == []
    assert pass3_ambiguous == []


def test_sibling_helper_replacement_stays_new_and_resolved_not_merged() -> None:
    pass2_still, pass2_new, pass2_resolved, pass2_ambiguous = _reconcile_sequence(
        head_sha="helper-pass-2",
        prior_pass=_build_prior_pass("helper-pass-1", [_helper_a_finding()]),
        findings=[_helper_b_finding()],
    )
    assert pass2_still == []
    assert pass2_new == ["src/helpers.py: Grouped payload helper now always raises"]
    assert pass2_resolved == ["src/helpers.py: Payload helper now always raises"]
    assert pass2_ambiguous == []


def test_llm_wording_drift_sequence_stays_still_unresolved_with_structured_fields() -> None:
    pass2_still, pass2_new, pass2_resolved, pass2_ambiguous = _reconcile_sequence(
        head_sha="llm-drift-pass-2",
        prior_pass=_build_prior_pass("llm-drift-pass-1", [_vehicle_details_finding()]),
        findings=[_vehicle_details_finding_llm_variant_a()],
    )
    assert pass2_still == [
        "bnl_app/functions/vehicle_functions.py: "
        "Unconditional ValueError breaks vehicle detail retrieval"
    ]
    assert pass2_new == []
    assert pass2_resolved == []
    assert pass2_ambiguous == []

    pass3_still, pass3_new, pass3_resolved, pass3_ambiguous = _reconcile_sequence(
        head_sha="llm-drift-pass-3",
        prior_pass=_build_prior_pass(
            "llm-drift-pass-2", [_vehicle_details_finding_llm_variant_a()]
        ),
        findings=[_vehicle_details_finding_llm_variant_b()],
    )
    assert pass3_still == [
        "bnl_app/functions/vehicle_functions.py: Vehicle details helper now always raises"
    ]
    assert pass3_new == []
    assert pass3_resolved == []
    assert pass3_ambiguous == []


def test_llm_wording_drift_sequence_survives_missing_structured_fields() -> None:
    pass2_still, pass2_new, pass2_resolved, pass2_ambiguous = _reconcile_sequence(
        head_sha="llm-unstructured-pass-2",
        prior_pass=_build_prior_pass("llm-unstructured-pass-1", [_vehicle_details_finding()]),
        findings=[_vehicle_details_finding_without_structured_fields()],
    )
    assert pass2_still == [
        "bnl_app/functions/vehicle_functions.py: "
        "Unconditional ValueError breaks vehicle detail retrieval"
    ]
    assert pass2_new == []
    assert pass2_resolved == []
    assert pass2_ambiguous == []


def test_same_unstructured_title_in_different_files_does_not_overlap() -> None:
    pass2_still, pass2_new, pass2_resolved, pass2_ambiguous = _reconcile_sequence(
        head_sha="cross-file-pass-2",
        prior_pass=_build_prior_pass("cross-file-pass-1", [_same_title_unstructured_file_a()]),
        findings=[_same_title_unstructured_file_b()],
    )
    assert pass2_still == []
    assert pass2_new == ["src/beta.py: Request path now always fails before lookup"]
    assert pass2_resolved == ["src/alpha.py: Request path now always fails before lookup"]
    assert pass2_ambiguous == []


def test_same_file_ambiguous_unstructured_overlap_stays_conservative() -> None:
    pass2_still, pass2_new, pass2_resolved, pass2_ambiguous = _reconcile_sequence(
        head_sha="ambiguous-pass-2",
        prior_pass=_build_prior_pass(
            "ambiguous-pass-1",
            [_ambiguous_prior_helper_a(), _ambiguous_prior_helper_b()],
        ),
        findings=[_ambiguous_current_helper()],
    )
    assert pass2_still == []
    assert pass2_new == []
    assert pass2_resolved == []
    assert pass2_ambiguous == [[0, 1]]


def test_same_symbol_severity_and_wording_drift_stays_still_unresolved() -> None:
    pass2_still, pass2_new, pass2_resolved, pass2_ambiguous = _reconcile_sequence(
        head_sha="severity-drift-pass-2",
        prior_pass=_build_prior_pass("severity-drift-pass-1", [_cache_guard_finding_high()]),
        findings=[_cache_guard_finding_low_wording_drift()],
    )
    assert pass2_still == ["src/cache.py: Cache key builder no longer guards missing tenant id"]
    assert pass2_new == []
    assert pass2_resolved == []
    assert pass2_ambiguous == []


def test_vehicle_types_continuity_survives_region_and_title_wording_drift() -> None:
    pass2_still, pass2_new, pass2_resolved, pass2_ambiguous = _reconcile_sequence(
        head_sha="vehicle-types-pass-2",
        prior_pass=_build_prior_pass("vehicle-types-pass-1", [_vehicle_types_prior_finding()]),
        findings=[_vehicle_types_current_wording_drift()],
    )

    assert pass2_still == [
        "core/external_clients/vehicle_lookup_service.py: "
        "Vehicle-based detail helpers assume `vehicle.types` is non-empty and can crash"
    ]
    assert pass2_new == []
    assert pass2_resolved == []
    assert pass2_ambiguous == []


def test_issue_kind_wording_drift_still_resolves_same_structured_finding() -> None:
    pass2_still, pass2_new, pass2_resolved, pass2_ambiguous = _reconcile_sequence(
        head_sha="issue-kind-drift-pass-2",
        prior_pass=_build_prior_pass("issue-kind-drift-pass-1", [_empty_types_prior_finding()]),
        findings=[_empty_types_current_issue_kind_drift()],
    )

    assert pass2_still == [
        "bnl_app/functions/vehicle_functions.py: "
        "UK/ROI details name fallback can index empty types"
    ]
    assert pass2_new == []
    assert pass2_resolved == []
    assert pass2_ambiguous == []
