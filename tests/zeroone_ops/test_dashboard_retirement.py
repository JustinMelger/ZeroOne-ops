"""Prevent retired dashboard runtime namespaces from re-entering application code."""

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "zeroone_ops"
RETIRED_NAMESPACES = (
    "zeroone_ops.models.dashboard",
    "zeroone_ops.providers.gitlab_dashboard_client",
    "zeroone_ops.services.dashboard",
    "zeroone_ops.services.intake.finding_dashboard_sync_service",
    "zeroone_ops.services.review.publish.review_dashboard_updater",
    "zeroone_ops.services.remediation.remediation_exclusion_service",
    "zeroone_ops.services.control_plane.work_items.remediation_work_item_promotion_service",
)


def test_retired_namespaces_have_no_runtime_definitions_or_imports():
    for namespace in RETIRED_NAMESPACES:
        target = SOURCE_ROOT.joinpath(*namespace.split(".")[1:])
        assert not target.with_suffix(".py").exists()
        assert not any(target.rglob("*.py"))
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
            for name in names:
                assert not any(
                    name == retired or name.startswith(retired + ".")
                    for retired in RETIRED_NAMESPACES
                ), f"{path}:{node.lineno} imports retired runtime {name}"
