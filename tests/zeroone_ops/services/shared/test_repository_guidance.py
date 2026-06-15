from pathlib import Path

from zeroone_ops.services.shared.repository_guidance import load_repository_guidance


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
