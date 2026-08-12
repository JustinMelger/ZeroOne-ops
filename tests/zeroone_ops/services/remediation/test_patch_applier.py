import subprocess
from pathlib import Path

import pytest

from zeroone_ops.models.analysis import PatchProposal
from zeroone_ops.services.remediation.patch_applier import (
    PatchApplier,
    PatchApplyError,
)


def _init_git_repo(repo_root: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)


@pytest.mark.parametrize("include_index_metadata", [False, True])
def test_apply_updates_file_from_unified_diff(
    tmp_path: Path,
    include_index_metadata: bool,
) -> None:
    repo_root = tmp_path
    _init_git_repo(repo_root)
    target = repo_root / "sample.txt"
    target.write_text("old\n", encoding="utf-8")
    proposal = PatchProposal(
        issue_key="AX1",
        files_touched=["sample.txt"],
        unified_diff=(
            "diff --git a/sample.txt b/sample.txt\n"
            + ("index 3367afd..3e75765 100644\n" if include_index_metadata else "")
            + "--- a/sample.txt\n"
            + "+++ b/sample.txt\n"
            + "@@ -1 +1 @@\n"
            + "-old\n"
            + "+new\n"
        ),
        commit_message="fix(sonar): update sample [AX1]",
        change_request_title="fix: update sample",
        change_request_description="summary",
    )

    PatchApplier(repo_root).apply(proposal)

    assert target.read_text(encoding="utf-8") == "new\n"


def test_apply_rejects_paths_outside_repo(tmp_path: Path) -> None:
    repo_root = tmp_path
    _init_git_repo(repo_root)
    proposal = PatchProposal(
        issue_key="AX1",
        files_touched=["../outside.txt"],
        unified_diff="diff --git a/../outside.txt b/../outside.txt\n",
        commit_message="fix(sonar): invalid [AX1]",
        change_request_title="fix: invalid",
        change_request_description="summary",
    )

    with pytest.raises(PatchApplyError, match="escapes repository root"):
        PatchApplier(repo_root).apply(proposal)


def test_apply_rejects_malformed_hunk_header_counts(tmp_path: Path) -> None:
    repo_root = tmp_path
    _init_git_repo(repo_root)
    target = repo_root / "sample.txt"
    target.write_text("old\n", encoding="utf-8")
    proposal = PatchProposal(
        issue_key="AX1",
        files_touched=["sample.txt"],
        unified_diff=(
            "diff --git a/sample.txt b/sample.txt\n"
            "--- a/sample.txt\n"
            "+++ b/sample.txt\n"
            "@@ -1,7 +1,7 @@\n"
            "-old\n"
            "+new\n"
        ),
        commit_message="fix(sonar): invalid sample [AX1]",
        change_request_title="fix: invalid sample",
        change_request_description="summary",
    )

    with pytest.raises(PatchApplyError, match="hunk header line counts do not match body"):
        PatchApplier(repo_root).apply(proposal)


@pytest.mark.parametrize(
    ("files_touched", "unified_diff", "message"),
    [
        (
            ["sample.txt", "other.txt"],
            (
                "diff --git a/sample.txt b/sample.txt\n"
                "--- a/sample.txt\n"
                "+++ b/sample.txt\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/other.txt b/other.txt\n"
                "--- a/other.txt\n"
                "+++ b/other.txt\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
            ),
            "must declare exactly one touched file",
        ),
        (
            ["sample.txt"],
            (
                "diff --git a/../outside.txt b/../outside.txt\n"
                "--- a/../outside.txt\n"
                "+++ b/../outside.txt\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
            ),
            "escapes repository root",
        ),
        (
            ["sample.txt"],
            (
                "diff --git a/sample.txt b/sample.txt\n"
                "--- a/sample.txt\n"
                "+++ b/other.txt\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
            ),
            "must describe the same path",
        ),
        (
            ["sample.txt"],
            (
                "diff --git a/sample.txt b/sample.txt\n"
                "new file mode 100644\n"
                "--- /dev/null\n"
                "+++ b/sample.txt\n"
                "@@ -0,0 +1 @@\n"
                "+new\n"
            ),
            "only in-place text edits",
        ),
        (
            ["sample.txt"],
            (
                "diff --git a/sample.txt b/renamed.txt\n"
                "similarity index 100%\n"
                "rename from sample.txt\n"
                "rename to renamed.txt\n"
            ),
            "renames are not supported",
        ),
        (
            ["sample.txt"],
            (
                "diff --git a/sample.txt b/sample.txt\n"
                "Binary files a/sample.txt and b/sample.txt differ\n"
            ),
            "only in-place text edits",
        ),
    ],
)
def test_validate_rejects_unsupported_or_out_of_scope_diff_paths(
    tmp_path: Path,
    files_touched: list[str],
    unified_diff: str,
    message: str,
) -> None:
    proposal = PatchProposal(
        issue_key="AX1",
        files_touched=files_touched,
        unified_diff=unified_diff,
        commit_message="fix: invalid patch",
        change_request_title="fix: invalid patch",
        change_request_description="summary",
    )

    with pytest.raises(PatchApplyError, match=message):
        PatchApplier(tmp_path).validate(proposal)
