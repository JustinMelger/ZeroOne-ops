from zeroone_ops.models.dashboard import DashboardItem
from zeroone_ops.services.dashboard.dashboard_item_normalizer import (
    DashboardItemNormalizer,
)


def build_item(
    *,
    item_id: str = "sonar:1",
    source: str = "sonarqube",
    item_type: str = "static_analysis_fix",
    status: str = "open",
    file_path: str | None = "src/service.py",
    source_reference: str = "AX123",
) -> DashboardItem:
    return DashboardItem(
        id=item_id,
        source=source,
        type=item_type,
        status=status,
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference=source_reference,
        file=file_path,
        line=42,
        rule="python:S1125",
        issue_type="CODE_SMELL",
        component="sample-project:src/service.py",
        project="sample-project",
        severity="LOW",
        source_severity="LOW",
        automation_severity="low",
        validation_commands=["uv run pytest"],
        expected_change="Use direct truthiness.",
        constraints="Single-file change only.",
        acceptance_criteria=["Tests pass."],
    )


def test_normalize_returns_provider_neutral_work_item_for_supported_dashboard_item() -> None:
    normalizer = DashboardItemNormalizer()

    result = normalizer.normalize(build_item())

    assert result.work_item is not None
    assert result.work_item.dashboard_item_id == "sonar:1"
    assert result.work_item.source_ref == "AX123"
    assert result.work_item.file_path == "src/service.py"
    assert result.work_item.validation_commands == ["uv run pytest"]
    assert result.work_item.severity == "low"
    assert result.work_item.issue_type == "CODE_SMELL"
    assert result.work_item.component == "sample-project:src/service.py"
    assert result.work_item.project == "sample-project"
    assert result.message == ""


def test_normalize_supports_static_analysis_items_from_any_finding_source() -> None:
    normalizer = DashboardItemNormalizer()

    result = normalizer.normalize(build_item(item_id="ruff-sarif:1", source="ruff-sarif"))

    assert result.work_item is not None
    assert result.work_item.source_type == "ruff-sarif"


def test_normalize_keeps_legacy_code_smell_items_supported() -> None:
    normalizer = DashboardItemNormalizer()

    result = normalizer.normalize(build_item(item_type="code_smell_fix"))

    assert result.work_item is not None


def test_normalize_keeps_legacy_lint_items_supported() -> None:
    normalizer = DashboardItemNormalizer()

    result = normalizer.normalize(build_item(source="ruff-sarif", item_type="lint_fix"))

    assert result.work_item is not None


def test_normalize_rejects_unsupported_item_type() -> None:
    normalizer = DashboardItemNormalizer()

    result = normalizer.normalize(build_item(item_type="pipeline_fix"))

    assert result.work_item is None
    assert result.message == "Dashboard item sonar:1 uses unsupported type pipeline_fix."


def test_normalize_rejects_missing_target_file_path() -> None:
    normalizer = DashboardItemNormalizer()

    result = normalizer.normalize(build_item(file_path=None))

    assert result.work_item is None
    assert result.message == "Dashboard item sonar:1 is missing a target file path."
