"""Safety contracts for copyable CI workflow templates."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_operational_templates_pin_zeroone_image_versions() -> None:
    template_paths = (
        "examples/github-operations.yml",
        "examples/github-review.yml",
        "examples/.gitlab-ci.example.yml",
    )
    for template_path in template_paths:
        template = (REPOSITORY_ROOT / template_path).read_text(encoding="utf-8")

        assert "zeroone-ops:latest" not in template
        assert "zeroone-ops:0.54.0" in template


def test_github_operations_uses_trusted_default_branch_checkout() -> None:
    template = (REPOSITORY_ROOT / "examples/github-operations.yml").read_text(encoding="utf-8")

    assert template.count("ref: ${{ github.event.repository.default_branch }}") == 5
    assert "setup and validation commands as executable CI policy" in template


def test_review_template_does_not_run_remediation_validation() -> None:
    template = (REPOSITORY_ROOT / "examples/github-review.yml").read_text(encoding="utf-8")

    assert "validation_setup_commands" not in template
    assert "validation_commands" not in template
    assert "never runs remediation setup or validation commands" in template


def test_gitlab_template_documents_protected_privileged_execution() -> None:
    template = (REPOSITORY_ROOT / "examples/.gitlab-ci.example.yml").read_text(encoding="utf-8")

    assert "masked and protected CI/CD variables" in template
    assert "protected default-branch configuration" in template
    assert "zeroone-ops control-plane run" in template
    assert "RUN_ZEROONE_OPS=true" in template
    assert "zeroone_ops_ruff_sarif" in template
    assert "zeroone_ops_mypy_sarif" in template
    assert "artifacts/ruff.sarif" in template
    assert "artifacts/mypy.sarif" in template
    assert 'python "$MYPY_TO_SARIF_SCRIPT"' in template
