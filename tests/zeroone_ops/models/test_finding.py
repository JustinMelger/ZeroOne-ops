from zeroone_ops.models.finding import (
    FindingCollectionMetadata,
    FindingCollectionResult,
    FindingSourceMetadata,
    NormalizedFinding,
    RemediationContext,
)


def test_normalized_finding_captures_shared_ingestion_contract() -> None:
    finding = NormalizedFinding(
        finding_id="src/service.py::python-s1125",
        source_id="sonarqube",
        severity="low",
        title="Simplify boolean comparison",
        summary="Replace explicit boolean equality with direct truthiness.",
        repository_path="src/service.py",
        line_start=42,
        line_end=42,
        region_hint="service-logic",
        remediation_context=RemediationContext(
            category="code_smell_fix",
            diagnostic_code="python:S1125",
            validation_commands=["uv run pytest"],
            expected_change="Use direct truthiness.",
            constraints="Single file only.",
            acceptance_criteria=["Tests pass."],
        ),
        source_metadata=FindingSourceMetadata(
            native_id="AX123",
            source_url="https://sonar.example.com/project/issues?id=AX123",
            attributes={"effort": "5min"},
        ),
    )

    assert finding.finding_id == "src/service.py::python-s1125"
    assert finding.source_id == "sonarqube"
    assert finding.repository_path == "src/service.py"
    assert finding.remediation_context.diagnostic_code == "python:S1125"
    assert finding.source_metadata is not None
    assert finding.source_metadata.native_id == "AX123"


def test_finding_collection_result_keeps_findings_and_collection_metadata() -> None:
    result = FindingCollectionResult(
        findings=[
            NormalizedFinding(
                finding_id="src/service.py::unknown",
                source_id="ruff-sarif",
                severity="medium",
                title="Avoid bare except",
                summary="The file catches all exceptions without narrowing scope.",
                repository_path="src/service.py",
            )
        ],
        metadata=FindingCollectionMetadata(
            source_id="ruff-sarif",
            source_revision="abc123",
            artifact_reference="artifacts/ruff.sarif",
            warnings=["One SARIF result had no stable native id."],
            statistics={"collected": 1},
        ),
    )

    assert result.metadata.source_id == "ruff-sarif"
    assert result.metadata.artifact_reference == "artifacts/ruff.sarif"
    assert result.metadata.statistics == {"collected": 1}
    assert result.findings[0].title == "Avoid bare except"
