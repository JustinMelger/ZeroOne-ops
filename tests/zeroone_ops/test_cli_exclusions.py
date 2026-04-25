import json
from pathlib import Path

from typer.testing import CliRunner

from zeroone_ops.cli import app

runner = CliRunner()


def write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / ".zeroone-ops.json"
    config_path.write_text(
        """
        {
          "base_branch": "main",
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    return config_path


def test_dashboard_exclusions_add_list_and_remove(tmp_path: Path, monkeypatch) -> None:
    config_path = write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(config_path))

    add_result = runner.invoke(
        app,
        [
            "dashboard",
            "exclusions",
            "add",
            "--source",
            "sonarqube",
            "--issue-key",
            "python:S3776",
            "--reason",
            "Usually requires broader refactor.",
            "--scope",
            "src/routers/",
            "--updated-by",
            "operator",
        ],
    )
    assert add_result.exit_code == 0
    assert "action=created" in add_result.stdout

    list_result = runner.invoke(app, ["dashboard", "exclusions", "list"])
    assert list_result.exit_code == 0
    assert "count=1" in list_result.stdout
    assert "source_count[sonarqube]=1" in list_result.stdout
    payload_line = list_result.stdout.strip().splitlines()[-1]
    payload = json.loads(payload_line)
    assert payload["source"] == "sonarqube"
    assert payload["issue_key"] == "python:S3776"
    assert payload["scope"] == "src/routers/"
    assert payload["updated_by"] == "operator"

    remove_result = runner.invoke(
        app,
        [
            "dashboard",
            "exclusions",
            "remove",
            "--source",
            "sonarqube",
            "--issue-key",
            "python:S3776",
            "--scope",
            "src/routers/",
        ],
    )
    assert remove_result.exit_code == 0
    assert "removed=true" in remove_result.stdout

    list_after_remove = runner.invoke(app, ["dashboard", "exclusions", "list"])
    assert list_after_remove.exit_code == 0
    assert "count=0" in list_after_remove.stdout


def test_dashboard_exclusions_add_replaces_existing_record(tmp_path: Path, monkeypatch) -> None:
    config_path = write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(config_path))

    first = runner.invoke(
        app,
        [
            "dashboard",
            "exclusions",
            "add",
            "--source",
            "pipeline_failure",
            "--issue-key",
            "mypy:arg-type",
            "--reason",
            "old reason",
        ],
    )
    assert first.exit_code == 0
    assert "action=created" in first.stdout

    second = runner.invoke(
        app,
        [
            "dashboard",
            "exclusions",
            "add",
            "--source",
            "pipeline_failure",
            "--issue-key",
            "mypy:arg-type",
            "--reason",
            "new reason",
        ],
    )
    assert second.exit_code == 0
    assert "action=replaced" in second.stdout

    listed = runner.invoke(app, ["dashboard", "exclusions", "list"])
    payload = json.loads(listed.stdout.strip().splitlines()[-1])
    assert payload["reason"] == "new reason"


def test_dashboard_exclusions_list_surfaces_grouped_source_counts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = write_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(config_path))

    first = runner.invoke(
        app,
        [
            "dashboard",
            "exclusions",
            "add",
            "--source",
            "sonarqube",
            "--issue-key",
            "python:S3776",
            "--reason",
            "Needs broader refactor.",
        ],
    )
    second = runner.invoke(
        app,
        [
            "dashboard",
            "exclusions",
            "add",
            "--source",
            "pipeline_failure",
            "--issue-key",
            "mypy:arg-type",
            "--reason",
            "Needs broader change.",
        ],
    )

    assert first.exit_code == 0
    assert second.exit_code == 0

    listed = runner.invoke(app, ["dashboard", "exclusions", "list"])

    assert listed.exit_code == 0
    assert "source_count[pipeline_failure]=1" in listed.stdout
    assert "source_count[sonarqube]=1" in listed.stdout
