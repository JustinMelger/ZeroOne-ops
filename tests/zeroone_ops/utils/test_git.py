from zeroone_ops.utils.git import build_remediation_branch_key


def test_build_remediation_branch_key_preserves_legacy_sonar_reference() -> None:
    assert build_remediation_branch_key(source="sonarqube", source_reference="AX-123") == "AX-123"


def test_build_remediation_branch_key_namespaces_non_sonar_reference() -> None:
    assert (
        build_remediation_branch_key(source="ruff-sarif", source_reference="AX-123")
        == "ruff-sarif-AX-123"
    )
