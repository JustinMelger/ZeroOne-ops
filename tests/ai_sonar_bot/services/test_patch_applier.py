import subprocess
from pathlib import Path

import pytest

from ai_sonar_bot.models.analysis import PatchProposal
from ai_sonar_bot.services.patch_applier import PatchApplier, PatchApplyError


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
        mr_title="fix: update sample",
        mr_description="summary",
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
        mr_title="fix: invalid",
        mr_description="summary",
    )

    with pytest.raises(PatchApplyError, match="escapes repository root"):
        PatchApplier(repo_root).apply(proposal)
