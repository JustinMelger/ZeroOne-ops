"""Contracts for the public documentation boundary and Pages deployment."""

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_PAGES = frozenset(
    {
        "index.md",
        "getting-started.md",
        "configuration.md",
        "workflows.md",
        "troubleshooting.md",
        "migration-v1.md",
        "runbook.md",
        "roadmap.md",
        "engineering-standards.md",
        "review-flow-mermaid.md",
        "review-bot-judgment-strategy.md",
    }
)
PUBLIC_ASSETS = frozenset({"assets/images/gitlab-demo-board.png"})
MAIN_ONLY = "github.event_name != 'pull_request' && github.ref == 'refs/heads/main'"


def _site_config() -> dict[str, Any]:
    return tomllib.loads((REPOSITORY_ROOT / "zensical.toml").read_text(encoding="utf-8"))["project"]


def _navigation_targets(entries: list[dict[str, Any]]) -> Iterator[str]:
    for entry in entries:
        for target in entry.values():
            if isinstance(target, list):
                yield from _navigation_targets(target)
            else:
                yield target


def test_site_navigation_exposes_only_selected_operator_docs() -> None:
    config = _site_config()
    assert config["site_url"] == "https://justinmelger.github.io/ZeroOne-ops/"
    assert config["docs_dir"] == "docs" and config["site_dir"] == "site"
    assert config["repo_url"] == "https://github.com/JustinMelger/ZeroOne-ops"
    assert config["edit_uri"] == "edit/main/docs/"
    assert [next(iter(entry)) for entry in config["nav"]] == [
        "Home",
        "Getting Started",
        "Configuration",
        "Workflows",
        "Troubleshooting",
        "Migration",
        "Reference",
    ]
    patterns = config["exclude_docs"].splitlines()
    assert patterns[0] == "*"
    assert set(patterns[1:]) == {f"!/{path}" for path in PUBLIC_PAGES | PUBLIC_ASSETS}
    local_targets = {
        target for target in _navigation_targets(config["nav"]) if not urlsplit(target).scheme
    }
    assert local_targets == PUBLIC_PAGES
    assert all((REPOSITORY_ROOT / "docs" / page).is_file() for page in local_targets)
    assert config["validation"] == {"invalid_links": True, "invalid_link_anchors": True}
    assert config["theme"]["variant"] == "modern"
    assert "plugins" not in config


def test_documentation_dependencies_are_not_runtime_dependencies() -> None:
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    docs = project["dependency-groups"]["docs"]
    assert any(requirement.startswith("zensical") for requirement in docs)
    assert any(requirement.startswith("pymdown-extensions") for requirement in docs)
    assert not any(
        requirement.startswith(("zensical", "pymdown-extensions"))
        for requirement in project["project"]["dependencies"]
    )
    assert "dev" in project["tool"]["uv"]["default-groups"]
    assert {"include-group": "docs"} in project["dependency-groups"]["dev"]
    assert project["tool"]["uv"]["exclude-newer"] == "7 days"


def test_pages_workflow_separates_read_only_build_from_main_deployment() -> None:
    workflow = yaml.load(
        (REPOSITORY_ROOT / ".github/workflows/documentation.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}
    build, deploy = workflow["jobs"]["build"], workflow["jobs"]["deploy"]
    assert "permissions" not in build and "environment" not in build
    commands = [step["run"] for step in build["steps"] if "run" in step]
    assert commands == [
        "uv sync --locked --only-group docs",
        "uv run --locked --only-group docs zensical build --clean --strict",
    ]
    upload = next(
        step for step in build["steps"] if "upload-pages-artifact@" in step.get("uses", "")
    )
    assert upload["if"] == MAIN_ONLY
    assert upload["with"]["path"] == "site"
    assert deploy["if"] == MAIN_ONLY and deploy["needs"] == "build"
    assert deploy["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}
    assert deploy["environment"] == {
        "name": "github-pages",
        "url": "${{ steps.deployment.outputs.page_url }}",
    }
    assert deploy["concurrency"] == {"group": "github-pages", "cancel-in-progress": "false"}
    deployment = next(step for step in deploy["steps"] if "deploy-pages@" in step.get("uses", ""))
    assert deployment["id"] == "deployment"
    for job in workflow["jobs"].values():
        assert "env" not in job and "secrets" not in job
        for step in job["steps"]:
            assert "env" not in step
            if "uses" in step:
                assert re.fullmatch(r"[\w-]+/[\w-]+@[a-f0-9]{40}", step["uses"])
    checkout = build["steps"][0]
    assert checkout["with"]["persist-credentials"] == "false"


def _build_documentation(root: Path, extra_index: str = "") -> subprocess.CompletedProcess[str]:
    """Build a public-only snapshot with private sentinels, without loading application code."""
    docs = root / "docs"
    docs.mkdir(parents=True)
    shutil.copyfile(REPOSITORY_ROOT / "zensical.toml", root / "zensical.toml")
    for page in PUBLIC_PAGES | PUBLIC_ASSETS:
        (docs / page).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY_ROOT / "docs" / page, docs / page)
    if extra_index:
        index = docs / "index.md"
        index.write_text(index.read_text(encoding="utf-8") + extra_index, encoding="utf-8")
    excluded_paths = {
        "README.md",
        "internal/private.md",
        "design/history.md",
        "unlisted.md",
        "assets/images/private.png",
    }
    excluded_paths.update(
        f"{folder}/{page}"
        for folder in ("internal", "design", "internal/nested")
        for page in PUBLIC_PAGES | PUBLIC_ASSETS
    )
    for excluded in excluded_paths:
        path = docs / excluded
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# PRIVATE_DOCS_SENTINEL\n", encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "zensical", "build", "--clean", "--strict"],
        cwd=root,
        env={**os.environ, "NO_COLOR": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.fixture(scope="module")
def built_documentation(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("documentation-site")
    result = _build_documentation(root)
    assert result.returncode == 0, result.stdout + result.stderr
    return root / "site"


def test_generated_pages_and_search_respect_public_allowlist(built_documentation: Path) -> None:
    expected = {"index.html", "404.html"} | {
        f"{Path(page).stem}/index.html" for page in PUBLIC_PAGES if page != "index.md"
    }
    assert {
        str(path.relative_to(built_documentation)) for path in built_documentation.rglob("*.html")
    } == expected
    assert not (built_documentation / "internal").exists()
    assert not (built_documentation / "design").exists()
    assert not (built_documentation / "assets/images/private.png").exists()
    search = json.loads((built_documentation / "search.json").read_text(encoding="utf-8"))
    allowed_locations = {""} | {
        f"{Path(page).stem}/" for page in PUBLIC_PAGES if page != "index.md"
    }
    assert search["items"]
    assert {entry["location"].split("#", 1)[0] for entry in search["items"]} <= allowed_locations
    assert "PRIVATE_DOCS_SENTINEL" not in json.dumps(search)


def test_demo_walkthrough_links_examples_and_publishes_only_its_snapshot(
    built_documentation: Path,
) -> None:
    getting_started = (built_documentation / "getting-started/index.html").read_text(
        encoding="utf-8"
    )
    home = (built_documentation / "index.html").read_text(encoding="utf-8")
    assert 'href="getting-started/#see-it-in-action"' in home
    assert 'id="see-it-in-action"' in getting_started
    for endpoint in ("boards#/", "work_items/58", "merge_requests/25"):
        assert f"https://gitlab.com/j.n.r.melger/zeroone-test-app/-/{endpoint}" in getting_started
    assert 'src="../assets/images/gitlab-demo-board.png"' in getting_started
    assert "intentionally seeded findings" in getting_started
    for relative_path in PUBLIC_ASSETS:
        published = (built_documentation / relative_path).read_bytes()
        assert published.startswith(b"\x89PNG\r\n\x1a\n")
        assert published == (REPOSITORY_ROOT / "docs" / relative_path).read_bytes()


def test_generated_site_preserves_markdown_features_and_project_subpath(
    built_documentation: Path,
) -> None:
    runbook = (built_documentation / "runbook/index.html").read_text(encoding="utf-8")
    assert "<table>" in runbook and "<pre" in runbook and "<code" in runbook
    assert 'id="json-config-quick-guide"' in runbook
    assert 'id="execution-trust-model"' in runbook
    assert 'href="https://justinmelger.github.io/ZeroOne-ops/runbook/"' in runbook
    assert 'href="../assets/stylesheets/' in runbook
    diagram = (built_documentation / "review-flow-mermaid/index.html").read_text(encoding="utf-8")
    assert '<pre class="mermaid"' in diagram
    assert "flowchart TD" in diagram
    home = (built_documentation / "index.html").read_text(encoding="utf-8")
    assert 'href="getting-started/"' in home
    assert 'href="./assets/stylesheets/' in home


@pytest.mark.parametrize(
    ("link", "diagnostic"),
    [
        ("missing-document.md", "page does not exist"),
        ("runbook.md#missing-anchor-for-regression", "anchor does not exist"),
    ],
)
def test_strict_build_rejects_broken_links_and_anchors(
    tmp_path: Path, link: str, diagnostic: str
) -> None:
    result = _build_documentation(tmp_path, f"\n[Broken reference]({link})\n")
    assert result.returncode != 0
    assert diagnostic in result.stdout + result.stderr
