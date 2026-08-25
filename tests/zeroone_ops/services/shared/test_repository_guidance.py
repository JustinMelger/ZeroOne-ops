import logging
from pathlib import Path

from zeroone_ops.services.shared.repository_guidance import (
    MAX_GUIDANCE_CHARS,
    MAX_GUIDANCE_LINES,
    load_repository_guidance,
)


def test_load_repository_guidance_returns_bounded_entries(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (tmp_path / "AGENT.md").write_text(
        "\n".join(
            [
                "# Agent Guide",
                "",
                "Use this repository guidance for fixes and reviews.",
                "",
                "- Prefer regression tests for behavior changes.",
                "- Keep services narrowly scoped.",
            ]
        ),
        encoding="utf-8",
    )
    (docs_dir / "technical-design-pr-review.md").write_text(
        "\n".join(
            [
                "# Technical Design",
                "",
                "Review notes should stay evidence-backed.",
                "",
                "## Standards",
                "- Prefer no findings over speculative comments.",
            ]
        ),
        encoding="utf-8",
    )

    guidance = load_repository_guidance(tmp_path)

    assert [entry.file_path for entry in guidance] == [
        "AGENT.md",
        "docs/technical-design-pr-review.md",
    ]
    assert "Prefer regression tests" in guidance[0].summary
    assert "Prefer no findings" in guidance[1].summary


def test_load_repository_guidance_uses_only_configured_paths_in_declared_order(
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (tmp_path / "AGENTS.md").write_text("# Default\nDefault guidance.\n", encoding="utf-8")
    (tmp_path / "CONTRIBUTING.md").write_text(
        "# Contributing\nConfigured contribution guidance.\n",
        encoding="utf-8",
    )
    (docs_dir / "engineering-standards.md").write_text(
        "# Standards\nConfigured standards guidance.\n",
        encoding="utf-8",
    )
    (docs_dir / "technical-design-pr-review.md").write_text(
        "# Technical Design\nDefault technical guidance.\n",
        encoding="utf-8",
    )
    (tmp_path / "directory").mkdir()

    guidance = load_repository_guidance(
        tmp_path,
        configured_paths=[
            "docs/engineering-standards.md",
            "missing.md",
            "directory",
            "CONTRIBUTING.md",
        ],
    )

    assert [entry.file_path for entry in guidance] == [
        "docs/engineering-standards.md",
        "CONTRIBUTING.md",
    ]


def test_load_repository_guidance_skips_navigation_and_preserves_markdown_blocks(
    tmp_path: Path,
) -> None:
    (tmp_path / "AGENTS.md").write_text(
        """# Agent Guide

Use this guide for repository work.

## Documentation

- [Architecture](docs/architecture.md)
- [Runbook](docs/runbook.md)
  - [Nested link](docs/nested.md)

## Working Rules

- Prefer regression tests; see [testing guidance](docs/testing.md).

> Keep provider integrations at the boundary.

```sh
uv run pytest tests/zeroone_ops/services/shared
```

## Malformed

- Keep malformed Markdown visible: [Unclosed link](docs/broken.md
""",
        encoding="utf-8",
    )

    guidance = load_repository_guidance(tmp_path)

    assert len(guidance) == 1
    summary = guidance[0].summary
    assert summary.startswith("## Working Rules")
    assert "Architecture" not in summary
    assert "Nested link" not in summary
    assert "Prefer regression tests; see [testing guidance](docs/testing.md)." in summary
    assert "> Keep provider integrations at the boundary." in summary
    assert "```sh\nuv run pytest tests/zeroone_ops/services/shared\n```" in summary
    assert "[Unclosed link](docs/broken.md" in summary


def test_load_repository_guidance_prioritizes_review_expectations(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        """# Agent Guide

Repository overview that should not exhaust guidance context.

## Repository Intent

More descriptive project context.

## Working Rules

- Keep services focused.

## Review Expectations

- Require evidence for behavior changes.
- Prefer bounded actionable findings.
""",
        encoding="utf-8",
    )

    guidance = load_repository_guidance(tmp_path)

    assert len(guidance) == 1
    summary = guidance[0].summary
    assert summary.startswith("## Review Expectations")
    assert "Require evidence for behavior changes." in summary
    assert "## Working Rules" in summary
    assert "Repository overview" not in summary


def test_load_repository_guidance_divides_context_across_top_sections(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        """## Review Expectations

- Check evidence.
- Prefer scoped findings.
- Keep findings concise.
- Require regression coverage.

## Working Rules

- Keep services focused.
- Prefer explicit dependencies.
- Use typed boundaries.
- Avoid hidden side effects.

## Coding Expectations

- Prefer composition.
- Keep constructors cheap.
- Use focused names.
- Avoid speculative abstractions.

## Repository Intent

This descriptive section should not displace operational guidance.
""",
        encoding="utf-8",
    )

    guidance = load_repository_guidance(tmp_path)

    assert len(guidance) == 1
    summary = guidance[0].summary
    assert "## Review Expectations" in summary
    assert "## Working Rules" in summary
    assert "## Coding Expectations" in summary
    assert "Repository Intent" not in summary
    assert len(summary.splitlines()) <= MAX_GUIDANCE_LINES


def test_load_repository_guidance_reserves_an_operational_section(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        """## Commands

Use `uv run pytest tests/unit` for focused validation.

```bash
uv run ruff check .
uv run mypy src
```

Run the smallest relevant test suite first, for example:

```bash
uv run pytest tests/unit
```

## API Development

- Use typed request and response models.
- Keep route handlers thin.
- Preserve response contracts.
- Avoid leaking backend payloads.

## Testing Expectations

- Add regression coverage.
- Prefer focused tests first.
- Keep test fixtures explicit.
- Run broader tests for shared changes.

## Architecture

- Keep dependencies inward.
- Keep routers independent from repositories.
- Use services for business rules.
- Keep transport details at the boundary.
""",
        encoding="utf-8",
    )

    guidance = load_repository_guidance(tmp_path)

    assert len(guidance) == 1
    summary = guidance[0].summary
    assert summary.startswith("## Commands")
    assert "uv run ruff check ." in summary
    assert "## Testing Expectations" in summary
    assert (
        "Run the smallest relevant test suite first" not in summary
        or "uv run pytest tests/unit" in summary
    )
    assert len(summary.splitlines()) <= MAX_GUIDANCE_LINES


def test_load_repository_guidance_bounds_one_oversized_block(tmp_path: Path) -> None:
    long_paragraph = "\n".join(f"line {number}" for number in range(40))
    (tmp_path / "AGENTS.md").write_text(long_paragraph, encoding="utf-8")

    guidance = load_repository_guidance(tmp_path)

    assert len(guidance) == 1
    assert guidance[0].summary.endswith("\n...")
    assert len(guidance[0].summary.splitlines()) == MAX_GUIDANCE_LINES


def test_load_repository_guidance_counts_block_separators_within_bounds(tmp_path: Path) -> None:
    blocks = "\n\n".join(f"## Rule {number}\nUse rule {number}." for number in range(20))
    (tmp_path / "AGENTS.md").write_text(blocks, encoding="utf-8")

    guidance = load_repository_guidance(tmp_path)

    assert len(guidance) == 1
    assert len(guidance[0].summary.splitlines()) <= MAX_GUIDANCE_LINES
    assert len(guidance[0].summary) <= MAX_GUIDANCE_CHARS


def test_load_repository_guidance_logs_selection_metadata_without_content(
    tmp_path: Path,
    caplog,
) -> None:
    guidance_text = """# Rules

- [Navigation](docs/navigation.md)
- Keep output deterministic.
"""
    (tmp_path / "AGENTS.md").write_text(guidance_text, encoding="utf-8")

    with caplog.at_level(logging.INFO):
        load_repository_guidance(tmp_path)

    assert "repository guidance selected" in caplog.text
    assert "path=AGENTS.md" in caplog.text
    assert "selected_lines=3" in caplog.text
    assert "skipped_navigation_items=1" in caplog.text
    assert "Keep output deterministic" not in caplog.text


def test_load_repository_guidance_skips_non_utf8_files_with_warning(
    tmp_path: Path,
    caplog,
) -> None:
    (tmp_path / "AGENTS.md").write_bytes(b"\xff\xfe")
    (tmp_path / "CONTRIBUTING.md").write_text("# Rules\nKeep tests focused.\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        guidance = load_repository_guidance(
            tmp_path,
            configured_paths=["AGENTS.md", "CONTRIBUTING.md"],
        )

    assert [entry.file_path for entry in guidance] == ["CONTRIBUTING.md"]
    assert "skipped unreadable repository guidance" in caplog.text
    assert "path=AGENTS.md" in caplog.text
    assert "error_type=UnicodeDecodeError" in caplog.text
