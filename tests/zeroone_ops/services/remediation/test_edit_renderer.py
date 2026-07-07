from pathlib import Path

import pytest

from zeroone_ops.models.analysis import StructuredEditProposal, TextEdit
from zeroone_ops.services.remediation.edit_renderer import (
    EditRenderer,
    EditRenderError,
)


def test_render_creates_patch_from_exact_text_replacement(tmp_path: Path) -> None:
    repo_root = tmp_path
    target = repo_root / "sample.py"
    target.write_text("if enabled == True:\n    print('x')\n", encoding="utf-8")
    proposal = StructuredEditProposal(
        issue_key="AX1",
        edits=[
            TextEdit(
                file_path="sample.py",
                search_text="enabled == True",
                replace_text="enabled",
            )
        ],
        commit_message="fix: simplify boolean comparison",
        change_request_title="fix: simplify boolean comparison",
        change_request_description="summary",
    )

    patch = EditRenderer(repo_root).render(proposal)

    assert patch.files_touched == ["sample.py"]
    assert "diff --git a/sample.py b/sample.py\n" in patch.unified_diff
    assert "-if enabled == True:\n" in patch.unified_diff
    assert "+if enabled:\n" in patch.unified_diff


def test_render_rejects_when_search_text_is_missing(tmp_path: Path) -> None:
    repo_root = tmp_path
    target = repo_root / "sample.py"
    target.write_text("value = 1\n", encoding="utf-8")
    proposal = StructuredEditProposal(
        issue_key="AX1",
        edits=[
            TextEdit(
                file_path="sample.py",
                search_text="value = 2",
                replace_text="value = 3",
            )
        ],
        commit_message="fix: update value",
        change_request_title="fix: update value",
        change_request_description="summary",
    )

    with pytest.raises(EditRenderError, match="Could not find exact search text"):
        EditRenderer(repo_root).render(proposal)


def test_render_rejects_ambiguous_repeated_match_without_line_hint(tmp_path: Path) -> None:
    repo_root = tmp_path
    target = repo_root / "sample.py"
    target.write_text("status_code = 1\nstatus_code = 2\n", encoding="utf-8")
    proposal = StructuredEditProposal(
        issue_key="AX1",
        edits=[
            TextEdit(
                file_path="sample.py",
                search_text="status_code",
                replace_text="_",
            )
        ],
        commit_message="fix: rename unused variable",
        change_request_title="fix: rename unused variable",
        change_request_description="summary",
    )

    with pytest.raises(EditRenderError, match="matched multiple locations"):
        EditRenderer(repo_root).render(proposal)


def test_render_uses_line_hint_to_disambiguate_match(tmp_path: Path) -> None:
    repo_root = tmp_path
    target = repo_root / "sample.py"
    target.write_text("status_code = 1\nstatus_code = 2\n", encoding="utf-8")
    proposal = StructuredEditProposal(
        issue_key="AX1",
        edits=[
            TextEdit(
                file_path="sample.py",
                search_text="status_code",
                replace_text="_",
                line_hint=2,
            )
        ],
        commit_message="fix: rename unused variable",
        change_request_title="fix: rename unused variable",
        change_request_description="summary",
    )

    patch = EditRenderer(repo_root).render(proposal)

    assert "-status_code = 2\n" in patch.unified_diff
    assert "+_ = 2\n" in patch.unified_diff


def test_render_supports_multiple_exact_edits_in_one_file(tmp_path: Path) -> None:
    repo_root = tmp_path
    target = repo_root / "sample.py"
    target.write_text(
        "value = cast(int, raw_value)\nresult = parse(value)\n",
        encoding="utf-8",
    )
    proposal = StructuredEditProposal(
        issue_key="AX1",
        edits=[
            TextEdit(
                file_path="sample.py",
                search_text="cast(int, raw_value)",
                replace_text="int(raw_value)",
            ),
            TextEdit(
                file_path="sample.py",
                search_text="parse(value)",
                replace_text="parse_int(value)",
            ),
        ],
        commit_message="fix: narrow local parsing flow",
        change_request_title="fix: narrow local parsing flow",
        change_request_description="summary",
    )

    patch = EditRenderer(repo_root).render(proposal)

    assert patch.files_touched == ["sample.py"]
    assert "-value = cast(int, raw_value)\n" in patch.unified_diff
    assert "+value = int(raw_value)\n" in patch.unified_diff
    assert "-result = parse(value)\n" in patch.unified_diff
    assert "+result = parse_int(value)\n" in patch.unified_diff
