from zeroone_ops.utils.finding_identity import build_fallback_finding_identity


def test_build_fallback_finding_identity_prefers_structured_fields() -> None:
    identity = build_fallback_finding_identity(
        repository_path="src/service.py",
        title="Simplify boolean comparison",
        summary="Replace explicit boolean equality with direct truthiness.",
        category="code_smell_fix",
        diagnostic_code="python:S1125",
        region_hint="service-logic",
    )

    assert identity == "src/service.py::code_smell_fix::python-s1125::service-logic"


def test_build_fallback_finding_identity_uses_title_and_summary_when_needed() -> None:
    identity = build_fallback_finding_identity(
        repository_path="src/service.py",
        title="Preferred supplier save path reports success",
        summary="The save path can return success without persisting supplier_ids.",
    )

    assert identity == "src/service.py::path-preferr-reports-save-success-supplier"


def test_build_fallback_finding_identity_returns_unknown_when_text_has_no_signal() -> None:
    identity = build_fallback_finding_identity(
        repository_path="src/service.py",
        title="An if",
        summary="Up to it.",
    )

    assert identity == "src/service.py::unknown"
