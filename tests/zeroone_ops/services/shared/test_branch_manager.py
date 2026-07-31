import subprocess
from pathlib import Path

import pytest

from zeroone_ops.services.shared.branch_manager import (
    BranchManager,
    BranchManagerError,
)


def _init_git_repo(repo_root: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.name", "ZeroOne Ops"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "zeroone-ops@example.com"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )


def test_ensure_ready_rejects_dirty_repository(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "sample.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(BranchManagerError, match="uncommitted or untracked"):
        BranchManager(tmp_path).ensure_ready()


def test_build_branch_name_is_predictable() -> None:
    branch_name = BranchManager(Path.cwd()).build_branch_name(
        branch_prefix="zeroone-ops",
        issue_key="AX-123",
        file_path="src/service.py",
    )

    assert branch_name == "zeroone-ops/ax-123/service"


def test_create_branch_and_commit_changes(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    tracked = tmp_path / "sample.txt"
    tracked.write_text("base\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "sample.txt"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    manager = BranchManager(tmp_path)
    manager.ensure_ready()
    manager.create_branch("zeroone-ops/ax-1/sample")
    tracked.write_text("updated\n", encoding="utf-8")

    commit_sha = manager.commit_and_push("fix(sonar): update sample [AX-1]", push=False)

    assert len(commit_sha) == 40
    current_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert current_branch == "zeroone-ops/ax-1/sample"
    assert tracked.read_text(encoding="utf-8") == "updated\n"


def test_commit_and_push_stages_only_requested_patch_files(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    tracked = tmp_path / "sample.txt"
    tracked.write_text("base\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "sample.txt"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked.write_text("updated\n", encoding="utf-8")
    bootstrap_output = tmp_path / "bootstrap-output.txt"
    bootstrap_output.write_text("generated\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "bootstrap-output.txt"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    BranchManager(tmp_path).commit_and_push(
        "fix: update sample",
        push=False,
        files_to_commit=["sample.txt"],
    )

    committed_files = subprocess.run(
        ["git", "show", "--format=", "--name-only", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert committed_files == ["sample.txt"]
    assert bootstrap_output.exists()
    assert (
        subprocess.run(
            ["git", "status", "--short"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == "?? bootstrap-output.txt\n"
    )
