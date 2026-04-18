from ai_sonar_bot.models.review import (
    MergeRequestReviewContext,
    PriorReviewContext,
    PriorReviewFinding,
    PriorReviewPass,
    ReviewFileContext,
    ReviewFinding,
    ReviewResult,
)
from ai_sonar_bot.services.review_finding_identity import (
    build_legacy_review_finding_identity,
    build_review_finding_identity,
)
from ai_sonar_bot.services.review_publisher import _reconcile_follow_up_review


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


def test_valueerror_sequence_tracks_still_unresolved_new_and_resolved_findings() -> None:
    pass1_findings = [_cylinder_finding()]

    pass2_findings = [_cylinder_finding(), _vehicle_details_finding()]
    pass2_reconciliation = _reconcile_follow_up_review(
        context=_build_context(
            head_sha="sha-pass-2",
            prior_pass=_build_prior_pass("sha-pass-1", pass1_findings),
        ),
        review_result=ReviewResult(
            classification="findings_present",
            summary="Two high-risk findings.",
            findings=pass2_findings,
        ),
    )

    assert pass2_reconciliation is not None
    assert [item.summary for item in pass2_reconciliation.still_unresolved] == [
        (
            "bnl_app/functions/vehicle_articles_functions.py: "
            "Function now always raises instead of returning cylinder count"
        )
    ]
    assert [item.summary for item in pass2_reconciliation.new_findings] == [
        "bnl_app/functions/vehicle_functions.py: "
        "Unconditional ValueError breaks vehicle detail retrieval"
    ]
    assert pass2_reconciliation.appears_resolved == []

    pass3_findings = [_cylinder_finding(), _vehicle_details_finding(), _filter_fields_finding()]
    pass3_reconciliation = _reconcile_follow_up_review(
        context=_build_context(
            head_sha="sha-pass-3",
            prior_pass=_build_prior_pass("sha-pass-2", pass2_findings),
        ),
        review_result=ReviewResult(
            classification="findings_present",
            summary="Three high-risk findings.",
            findings=pass3_findings,
        ),
    )

    assert pass3_reconciliation is not None
    assert [item.summary for item in pass3_reconciliation.still_unresolved] == [
        (
            "bnl_app/functions/vehicle_articles_functions.py: "
            "Function now always raises instead of returning cylinder count"
        ),
        "bnl_app/functions/vehicle_functions.py: "
        "Unconditional ValueError breaks vehicle detail retrieval",
    ]
    assert [item.summary for item in pass3_reconciliation.new_findings] == [
        "bnl_app/functions/vehicle_functions.py: "
        "Shared field-filtering helper now throws for all callers"
    ]
    assert pass3_reconciliation.appears_resolved == []

    pass4_findings = [_cylinder_finding(), _vehicle_details_finding()]
    pass4_reconciliation = _reconcile_follow_up_review(
        context=_build_context(
            head_sha="sha-pass-4",
            prior_pass=_build_prior_pass("sha-pass-3", pass3_findings),
        ),
        review_result=ReviewResult(
            classification="findings_present",
            summary="Two high-risk findings.",
            findings=pass4_findings,
        ),
    )

    assert pass4_reconciliation is not None
    assert [item.summary for item in pass4_reconciliation.still_unresolved] == [
        (
            "bnl_app/functions/vehicle_articles_functions.py: "
            "Function now always raises instead of returning cylinder count"
        ),
        "bnl_app/functions/vehicle_functions.py: "
        "Unconditional ValueError breaks vehicle detail retrieval",
    ]
    assert pass4_reconciliation.new_findings == []
    assert [item.summary for item in pass4_reconciliation.appears_resolved] == [
        "bnl_app/functions/vehicle_functions.py: "
        "Shared field-filtering helper now throws for all callers"
    ]


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


def test_wording_drift_sequence_keeps_same_concern_still_unresolved() -> None:
    pass1_findings = [_ordering_finding_original()]

    pass2_findings = [_ordering_finding_wording_drift()]
    pass2_reconciliation = _reconcile_follow_up_review(
        context=_build_context(
            head_sha="ordering-pass-2",
            prior_pass=_build_prior_pass("ordering-pass-1", pass1_findings),
        ),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
            findings=pass2_findings,
        ),
    )

    assert pass2_reconciliation is not None
    assert [item.summary for item in pass2_reconciliation.still_unresolved] == [
        "src/service.py: Ordering regression"
    ]
    assert pass2_reconciliation.new_findings == []
    assert pass2_reconciliation.appears_resolved == []

    pass3_findings = [_ordering_finding_original()]
    pass3_reconciliation = _reconcile_follow_up_review(
        context=_build_context(
            head_sha="ordering-pass-3",
            prior_pass=_build_prior_pass("ordering-pass-2", pass2_findings),
        ),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
            findings=pass3_findings,
        ),
    )

    assert pass3_reconciliation is not None
    assert [item.summary for item in pass3_reconciliation.still_unresolved] == [
        "src/service.py: Ordering logic now returns a different sequence"
    ]
    assert pass3_reconciliation.new_findings == []
    assert pass3_reconciliation.appears_resolved == []


def test_sibling_helper_sequence_marks_removed_and_new_separately() -> None:
    pass1_findings = [_helper_a_finding()]

    pass2_findings = [_helper_b_finding()]
    pass2_reconciliation = _reconcile_follow_up_review(
        context=_build_context(
            head_sha="helper-pass-2",
            prior_pass=_build_prior_pass("helper-pass-1", pass1_findings),
        ),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One high-risk finding.",
            findings=pass2_findings,
        ),
    )

    assert pass2_reconciliation is not None
    assert pass2_reconciliation.still_unresolved == []
    assert [item.summary for item in pass2_reconciliation.new_findings] == [
        "src/helpers.py: Grouped payload helper now always raises"
    ]
    assert [item.summary for item in pass2_reconciliation.appears_resolved] == [
        "src/helpers.py: Payload helper now always raises"
    ]


def _vehicle_details_finding_llm_variant_a() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="bnl_app/functions/vehicle_functions.py",
        symbol="get_vehicle_details_long",
        issue_kind="unconditional_exception",
        region_hint="function-entry",
        title="Vehicle details helper now always raises",
        evidence="An unconditional ValueError is raised before any helper logic can run.",
        explanation=(
            "All requests that reach this helper now fail before vehicle details are built."
        ),
        suggested_follow_up=(
            "Remove the unconditional exception and restore the existing helper flow."
        ),
    )


def _vehicle_details_finding_llm_variant_b() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="bnl_app/functions/vehicle_functions.py",
        symbol="get_vehicle_details_long",
        issue_kind="unconditional_exception",
        region_hint="function-entry",
        title="Long vehicle-details path is aborted on every call",
        evidence="The patch raises ValueError at function entry before any detail retrieval runs.",
        explanation="The long-details path is deterministically terminated for all callers.",
        suggested_follow_up="Delete the unconditional raise and restore the lookup path.",
    )


def _vehicle_details_finding_without_structured_fields() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="bnl_app/functions/vehicle_functions.py",
        title="Vehicle details path now always fails before lookup",
        evidence="The diff adds an unconditional ValueError before the helper body executes.",
        explanation="The helper now raises before any existing vehicle detail logic can run.",
        suggested_follow_up="Remove the unconditional raise and restore the helper body.",
    )


def test_llm_wording_drift_sequence_keeps_same_vehicle_detail_concern() -> None:
    pass1_findings = [_vehicle_details_finding()]

    pass2_findings = [_vehicle_details_finding_llm_variant_a()]
    pass2_reconciliation = _reconcile_follow_up_review(
        context=_build_context(
            head_sha="llm-drift-pass-2",
            prior_pass=_build_prior_pass("llm-drift-pass-1", pass1_findings),
        ),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One high-risk finding.",
            findings=pass2_findings,
        ),
    )

    assert pass2_reconciliation is not None
    assert [item.summary for item in pass2_reconciliation.still_unresolved] == [
        "bnl_app/functions/vehicle_functions.py: "
        "Unconditional ValueError breaks vehicle detail retrieval"
    ]
    assert pass2_reconciliation.new_findings == []
    assert pass2_reconciliation.appears_resolved == []

    pass3_findings = [_vehicle_details_finding_llm_variant_b()]
    pass3_reconciliation = _reconcile_follow_up_review(
        context=_build_context(
            head_sha="llm-drift-pass-3",
            prior_pass=_build_prior_pass("llm-drift-pass-2", pass2_findings),
        ),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One high-risk finding.",
            findings=pass3_findings,
        ),
    )

    assert pass3_reconciliation is not None
    assert [item.summary for item in pass3_reconciliation.still_unresolved] == [
        "bnl_app/functions/vehicle_functions.py: Vehicle details helper now always raises"
    ]
    assert pass3_reconciliation.new_findings == []
    assert pass3_reconciliation.appears_resolved == []


def test_llm_wording_drift_sequence_survives_missing_structured_fields() -> None:
    pass1_findings = [_vehicle_details_finding_llm_variant_a()]

    pass2_findings = [_vehicle_details_finding_without_structured_fields()]
    pass2_reconciliation = _reconcile_follow_up_review(
        context=_build_context(
            head_sha="llm-unstructured-pass-2",
            prior_pass=_build_prior_pass("llm-unstructured-pass-1", pass1_findings),
        ),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One high-risk finding.",
            findings=pass2_findings,
        ),
    )

    assert pass2_reconciliation is not None
    assert [item.summary for item in pass2_reconciliation.still_unresolved] == [
        "bnl_app/functions/vehicle_functions.py: Vehicle details helper now always raises"
    ]
    assert pass2_reconciliation.new_findings == []
    assert pass2_reconciliation.appears_resolved == []


def _cache_guard_finding_high() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/cache.py",
        symbol="Cache.load",
        issue_kind="missing_guard",
        region_hint="function-entry",
        title="Cache loader misses empty-key guard",
        evidence="The diff removes the early empty-key check before cache lookup.",
        explanation="Empty keys can now flow into the cache lookup path.",
        suggested_follow_up="Restore the empty-key guard before lookup.",
    )


def _cache_guard_finding_low_wording_drift() -> ReviewFinding:
    return ReviewFinding(
        severity="low",
        file_path="src/cache.py",
        symbol="Cache.load",
        issue_kind="missing_guard",
        region_hint="function-entry",
        title="Cache lookup now accepts empty keys",
        evidence="The early guard is removed, so empty keys reach the lookup path.",
        explanation="The cache loader now allows empty keys into the same lookup flow.",
        suggested_follow_up="Reinstate the guard before cache access.",
    )


def _same_title_unstructured_file_a() -> ReviewFinding:
    return ReviewFinding(
        severity="medium",
        file_path="src/alpha.py",
        title="Request path now always fails before lookup",
        evidence="An unconditional exception is raised before the helper body runs.",
        explanation="The request path now fails before any lookup logic executes.",
        suggested_follow_up="Remove the unconditional raise and restore the helper flow.",
    )


def _same_title_unstructured_file_b() -> ReviewFinding:
    return ReviewFinding(
        severity="medium",
        file_path="src/beta.py",
        title="Request path now always fails before lookup",
        evidence="An unconditional exception is raised before the helper body runs.",
        explanation="The request path now fails before any lookup logic executes.",
        suggested_follow_up="Remove the unconditional raise and restore the helper flow.",
    )


def _ambiguous_prior_helper_a() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/helpers.py",
        title="Vehicle payload helper now fails before assembly",
        evidence="The change raises before payload assembly starts.",
        explanation="Payload assembly callers now fail immediately.",
        suggested_follow_up="Restore the payload assembly path.",
    )


def _ambiguous_prior_helper_b() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/helpers.py",
        title="Vehicle payload helper now fails before grouping",
        evidence="The change raises before grouped payload logic starts.",
        explanation="Grouped payload callers now fail immediately.",
        suggested_follow_up="Restore the grouped payload path.",
    )


def _ambiguous_current_helper() -> ReviewFinding:
    return ReviewFinding(
        severity="high",
        file_path="src/helpers.py",
        title="Vehicle payload helper now fails before processing",
        evidence="The helper raises before the main payload logic runs.",
        explanation="Payload processing now aborts before helper logic completes.",
        suggested_follow_up="Remove the unconditional raise and restore helper execution.",
    )


def test_same_title_in_different_files_does_not_overlap() -> None:
    pass1_findings = [_same_title_unstructured_file_a()]

    pass2_findings = [_same_title_unstructured_file_b()]
    pass2_reconciliation = _reconcile_follow_up_review(
        context=_build_context(
            head_sha="cross-file-pass-2",
            prior_pass=_build_prior_pass("cross-file-pass-1", pass1_findings),
        ),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
            findings=pass2_findings,
        ),
    )

    assert pass2_reconciliation is not None
    assert pass2_reconciliation.still_unresolved == []
    assert [item.summary for item in pass2_reconciliation.new_findings] == [
        "src/beta.py: Request path now always fails before lookup"
    ]
    assert [item.summary for item in pass2_reconciliation.appears_resolved] == [
        "src/alpha.py: Request path now always fails before lookup"
    ]


def test_ambiguous_same_file_unstructured_match_stays_conservative() -> None:
    pass1_findings = [_ambiguous_prior_helper_a(), _ambiguous_prior_helper_b()]

    pass2_findings = [_ambiguous_current_helper()]
    pass2_reconciliation = _reconcile_follow_up_review(
        context=_build_context(
            head_sha="ambiguous-pass-2",
            prior_pass=_build_prior_pass("ambiguous-pass-1", pass1_findings),
        ),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One high-risk finding.",
            findings=pass2_findings,
        ),
    )

    assert pass2_reconciliation is not None
    assert pass2_reconciliation.still_unresolved == []
    assert [item.summary for item in pass2_reconciliation.new_findings] == [
        "src/helpers.py: Vehicle payload helper now fails before processing"
    ]
    assert [item.summary for item in pass2_reconciliation.appears_resolved] == [
        "src/helpers.py: Vehicle payload helper now fails before assembly",
        "src/helpers.py: Vehicle payload helper now fails before grouping",
    ]


def test_same_symbol_with_severity_and_wording_drift_stays_unresolved() -> None:
    pass1_findings = [_cache_guard_finding_high()]

    pass2_findings = [_cache_guard_finding_low_wording_drift()]
    pass2_reconciliation = _reconcile_follow_up_review(
        context=_build_context(
            head_sha="severity-drift-pass-2",
            prior_pass=_build_prior_pass("severity-drift-pass-1", pass1_findings),
        ),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One low-risk finding.",
            findings=pass2_findings,
        ),
    )

    assert pass2_reconciliation is not None
    assert [item.summary for item in pass2_reconciliation.still_unresolved] == [
        "src/cache.py: Cache loader misses empty-key guard"
    ]
    assert pass2_reconciliation.new_findings == []
    assert pass2_reconciliation.appears_resolved == []
