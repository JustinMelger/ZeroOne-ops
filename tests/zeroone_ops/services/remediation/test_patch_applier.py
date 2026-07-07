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


def test_apply_updates_file_from_unified_diff(tmp_path: Path) -> None:
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
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
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
