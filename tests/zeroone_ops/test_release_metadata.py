"""Keep release bumps compatible with locked documentation installation."""

import json
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_release_updates_the_local_lockfile_package_version() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    config = json.loads((ROOT / "release-please-config.json").read_text())
    # Release Please's TOML selector exposes scalar tokens through their value field.
    expected = {
        "type": "toml",
        "path": "uv.lock",
        "jsonpath": f"$.package[?(@.name.value=='{project['name']}')].version",
    }
    assert expected in config["packages"]["."]["extra-files"]


def test_project_lockfile_and_release_manifest_versions_match() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    locked = tomllib.loads((ROOT / "uv.lock").read_text())
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
    local_packages = [
        package for package in locked["package"] if package["name"] == project["name"]
    ]
    assert len(local_packages) == 1
    assert local_packages[0]["source"] == {"editable": "."}
    assert local_packages[0]["version"] == project["version"] == manifest["."]


def test_release_action_uses_manifest_configuration_without_overriding_strategy() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/release-please.yml").read_text())
    steps = workflow["jobs"]["release-please"]["steps"]
    action = next(
        step
        for step in steps
        if step.get("uses", "").startswith("googleapis/release-please-action@")
    )
    assert action["with"]["config-file"] == "release-please-config.json"
    assert action["with"]["manifest-file"] == ".release-please-manifest.json"
    assert "release-type" not in action["with"]
