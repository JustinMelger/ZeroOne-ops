from zeroone_ops.models.remediation import RemediationWorkItem


def test_remediation_work_item_captures_provider_neutral_fields() -> None:
    work_item = RemediationWorkItem(
        dashboard_item_id="sonar:1",
        source_type="sonarqube",
        source_ref="project:src/service.py",
        title="Simplify boolean comparison",
        status="open",
        message="Replace explicit boolean equality with direct truthiness.",
        file_path="src/service.py",
        line=42,
        rule_id="python:S1125",
        severity="LOW",
        source_payload={"source": "sonarqube"},
        validation_commands=["uv run pytest"],
        expected_change="Use direct truthiness.",
        constraints="Single file only.",
        acceptance_criteria=["Tests pass."],
    )

    assert work_item.dashboard_item_id == "sonar:1"
    assert work_item.rule_id == "python:S1125"
    assert work_item.source_payload == {"source": "sonarqube"}
    assert work_item.validation_commands == ["uv run pytest"]
