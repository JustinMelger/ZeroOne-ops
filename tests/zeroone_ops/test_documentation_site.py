"""Contracts for the public documentation boundary and Pages deployment."""

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

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
PUBLIC_ASSETS = frozenset(
    {
        "assets/images/gitlab-demo-board.png",
        "assets/images/zeroone-mark.svg",
        "assets/stylesheets/zeroone.css",
    }
)
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


def test_styling_uses_supported_theme_configuration_and_explicit_assets() -> None:
    config = _site_config()
    assert config["extra_css"] == ["assets/stylesheets/zeroone.css"]
    assert config["theme"]["logo"] == config["theme"]["favicon"] == "assets/images/zeroone-mark.svg"
    assert config["theme"]["font"] == {"text": "IBM Plex Sans", "code": "IBM Plex Mono"}
    assert config["theme"]["palette"] == {
        "scheme": "default",
        "primary": "custom",
        "accent": "custom",
    }
    assert "extra_javascript" not in config and "custom_dir" not in config["theme"]


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
        "assets/images/private.svg",
        "assets/stylesheets/private.css",
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
    assert not (built_documentation / "assets/images/private.svg").exists()
    assert not (built_documentation / "assets/stylesheets/private.css").exists()
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
        if relative_path.endswith(".png"):
            assert published.startswith(b"\x89PNG\r\n\x1a\n")
        assert published == (REPOSITORY_ROOT / "docs" / relative_path).read_bytes()


class _PageElements(HTMLParser):
    """Read generated markup without coupling contracts to full HTML snapshots."""

    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.card_links: list[str | None] = []
        self._card_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
        if tag == "div" and (
            self._card_depth or "zeroone-start" in (attributes.get("class") or "").split()
        ):
            self._card_depth += 1
        if tag == "a" and self._card_depth:
            self.card_links.append(attributes.get("href"))

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._card_depth:
            self._card_depth -= 1


def test_homepage_uses_native_cards_actions_and_preserved_anchors(
    built_documentation: Path,
) -> None:
    page = _PageElements()
    html = (built_documentation / "index.html").read_text(encoding="utf-8")
    page.feed(html)
    anchors = {attrs.get("id") for _, attrs in page.elements}
    assert {"zeroone-ops", "start-operating", "detailed-reference"} <= anchors
    actions = {
        attrs["href"]
        for tag, attrs in page.elements
        if tag == "a" and "md-button" in (attrs.get("class") or "").split()
    }
    assert actions == {"getting-started/", "getting-started/#see-it-in-action"}
    assert any(
        {"grid", "cards", "zeroone-start"} <= set((attrs.get("class") or "").split())
        for _, attrs in page.elements
    )
    assert page.card_links == ["configuration/", "workflows/", "troubleshooting/", "migration-v1/"]
    assert "Documentation version" in html and "<code>main</code>" in html
    assert any(
        {"admonition", "info"} <= set((attrs.get("class") or "").split())
        for _, attrs in page.elements
    )


@pytest.mark.parametrize(
    "page_path", ["index.html", "runbook/index.html", "configuration/index.html"]
)
def test_brand_assets_resolve_under_project_subpath(
    built_documentation: Path, page_path: str
) -> None:
    page = _PageElements()
    page.feed((built_documentation / page_path).read_text(encoding="utf-8"))
    root = _site_config()["site_url"]
    current = urljoin(
        root, "" if page_path == "index.html" else page_path.removesuffix("index.html")
    )
    found: set[str] = set()
    for tag, attrs in page.elements:
        reference = attrs.get("src" if tag == "img" else "href")
        if not reference or not reference.endswith(("zeroone.css", "zeroone-mark.svg")):
            continue
        absolute = urljoin(current, reference)
        assert absolute.startswith(root)
        relative = absolute.removeprefix(root)
        assert relative in PUBLIC_ASSETS
        assert (built_documentation / relative).is_file()
        found.add(relative)
    assert found == {"assets/stylesheets/zeroone.css", "assets/images/zeroone-mark.svg"}


def test_documentation_palette_has_accessible_text_contrast() -> None:
    css = (REPOSITORY_ROOT / "docs/assets/stylesheets/zeroone.css").read_text(encoding="utf-8")
    tokens = dict(re.findall(r"(--zeroone-[\w-]+):\s*(#[a-fA-F0-9]{6});", css))

    def luminance(color: str) -> float:
        channels = [int(color[offset : offset + 2], 16) / 255 for offset in (1, 3, 5)]
        linear = [
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            for value in channels
        ]
        return sum(
            value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True)
        )

    for foreground in ("ink", "muted", "teal", "teal-dark"):
        for background in ("canvas", "surface", "tint"):
            values = sorted(
                (
                    luminance(tokens[f"--zeroone-{foreground}"]),
                    luminance(tokens[f"--zeroone-{background}"]),
                )
            )
            assert (values[1] + 0.05) / (values[0] + 0.05) >= 4.5, (foreground, background)


def test_roadmap_milestones_are_implemented_capabilities_not_future_work(
    built_documentation: Path,
) -> None:
    source = (REPOSITORY_ROOT / "docs/roadmap.md").read_text(encoding="utf-8")
    block = source.split('<div class="zeroone-milestones" markdown="1">', 1)[1].split("</div>", 1)[
        0
    ]
    titles = re.findall(r"^- \*\*(.+)\*\*$", block, re.MULTILINE)
    assert titles and len(titles) == len(set(titles))
    assert "## Current Focus" not in block and "## Parked For Later" not in block
    assert "not a dated release sequence" in source
    html = (built_documentation / "roadmap/index.html").read_text(encoding="utf-8")
    timeline = html.split('<div class="zeroone-milestones">', 1)[1].split("</div>", 1)[0]
    assert timeline.count("<ul>") == 1 and timeline.count("<li>") == len(titles)
    entries = re.findall(r"<li>(.*?)</li>", timeline, re.DOTALL)
    assert all(entry.count("<p>") >= 2 for entry in entries)
    for title in titles:
        assert f"<strong>{title}</strong>" in timeline
    assert 'href="#remediation-batching"' in timeline
    assert 'href="../migration-v1/"' in timeline
    assert 'id="current-focus"' in html and 'id="parked-for-later-post-v1"' in html
    assert "zeroone-milestones" not in (built_documentation / "index.html").read_text(
        encoding="utf-8"
    )


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
