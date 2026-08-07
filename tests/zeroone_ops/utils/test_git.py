from zeroone_ops.utils.git import (
    build_remediation_branch_lookup_names,
    build_remediation_branch_name,
)


def test_build_remediation_branch_name_uses_canonical_source_and_reference_segments() -> None:
    assert (
        build_remediation_branch_name(
            branch_prefix="zeroone-ops",
            source="sonarqube",
            source_reference="AX-123",
            file_path="src/service.py",
        )
        == "zeroone-ops/sonarqube-0f1141ab4d989706/ax-123-0fcad5aa5945363d/service"
    )


def test_build_remediation_branch_name_distinguishes_ambiguous_source_reference_pairs() -> None:
    first_branch = build_remediation_branch_name(
        branch_prefix="zeroone-ops",
        source="tool-a",
        source_reference="finding",
        file_path="src/service.py",
    )
    second_branch = build_remediation_branch_name(
        branch_prefix="zeroone-ops",
        source="tool",
        source_reference="a-finding",
        file_path="src/service.py",
    )

    assert first_branch != second_branch


def test_build_remediation_branch_name_bounds_long_finding_references() -> None:
    branch_name = build_remediation_branch_name(
        branch_prefix="zeroone-ops",
        source="ruff-sarif",
        source_reference=(
            "src/zeroone_ops/services/review/pipeline/"
            "review_candidate_generation_service.py::lint_fix::sim114::"
            "lines-330-336-cols-5-48::branches-combine-logical-operator-using"
        ),
        file_path="src/zeroone_ops/services/review/pipeline/review_candidate_generation_service.py",
    )

    # GitHub accepts refs/heads/<branch> only when the complete ref is at most 255 bytes.
    assert len(f"refs/heads/{branch_name}") <= 255
    assert branch_name.endswith("/review-candidate-generation-serv")


def test_build_remediation_branch_name_uses_ascii_for_non_ascii_identifiers() -> None:
    branch_name = build_remediation_branch_name(
        branch_prefix="zeroone-ops",
        source="ruff-sarif",
        source_reference="finding-€",
        file_path="src/caf\u00e9.py",
    )

    assert branch_name.isascii()


def test_build_remediation_branch_name_distinguishes_fresh_attempts() -> None:
    first_attempt = build_remediation_branch_name(
        branch_prefix="zeroone-ops",
        source="ruff-sarif",
        source_reference="C416:src/service.py:12",
        file_path="src/service.py",
    )
    second_attempt = build_remediation_branch_name(
        branch_prefix="zeroone-ops",
        source="ruff-sarif",
        source_reference="C416:src/service.py:12",
        file_path="src/service.py",
        attempt_number=2,
    )

    assert second_attempt == f"{first_attempt}/attempt-2"
    assert len(f"refs/heads/{second_attempt}") <= 255


def test_build_remediation_branch_name_rejects_invalid_attempt_number() -> None:
    try:
        build_remediation_branch_name(
            branch_prefix="zeroone-ops",
            source="ruff-sarif",
            source_reference="C416:src/service.py:12",
            file_path="src/service.py",
            attempt_number=0,
        )
    except ValueError as error:
        assert str(error) == "Remediation attempt number must be at least one."
    else:  # pragma: no cover - assertion for an unexpected accepted input
        raise AssertionError("Expected an invalid remediation attempt number to be rejected.")


def test_build_remediation_branch_lookup_names_includes_legacy_sonar_branch() -> None:
    assert build_remediation_branch_lookup_names(
        branch_prefix="zeroone-ops",
        source="sonarqube",
        source_reference="AX-123",
        file_path="src/service.py",
    ) == (
        "zeroone-ops/sonarqube-0f1141ab4d989706/ax-123-0fcad5aa5945363d/service",
        "zeroone-ops/ax-123/service",
    )


def test_build_remediation_branch_lookup_names_uses_only_canonical_non_sonar_branch() -> None:
    assert build_remediation_branch_lookup_names(
        branch_prefix="zeroone-ops",
        source="ruff-sarif",
        source_reference="AX-123",
        file_path="src/service.py",
    ) == ("zeroone-ops/ruff-sarif-9fb4ba99a4827142/ax-123-0fcad5aa5945363d/service",)
