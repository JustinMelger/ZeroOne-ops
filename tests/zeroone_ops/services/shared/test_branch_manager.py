import logging
import subprocess
from pathlib import Path

import pytest

from zeroone_ops.services.shared.branch_manager import (
    BranchManager,
    BranchManagerError,
    _format_dirty_workspace_message,
)
from zeroone_ops.services.shared.runtime_workspace import (
    RuntimeWorkspacePolicy,
    parse_porcelain_status,
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
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "mypy.sarif").write_text("{}\n", encoding="utf-8")
    (tmp_path / ".zeroone-ops-state.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(BranchManagerError) as error:
        BranchManager(tmp_path).ensure_ready()

    assert str(error.value) == (
        "Repository has uncommitted or untracked changes:\n"
        "- untracked: .zeroone-ops-state.json\n"
        "- untracked: artifacts/mypy.sarif\n"
        "Ignore generated runtime files or clean the workspace before retrying."
    )


def test_ensure_ready_uses_safe_decoding_for_non_utf8_filenames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[dict[str, object]] = []

    def run_git_command(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(kwargs)
        command = args[0]
        assert isinstance(command, list)
        stdout = (
            "true"
            if command[1:3] == ["rev-parse", "--is-inside-work-tree"]
            else "?? generated-\\xff.txt\0"
        )
        return subprocess.CompletedProcess(command, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(
        "zeroone_ops.services.shared.branch_manager.subprocess.run",
        run_git_command,
    )

    with pytest.raises(BranchManagerError) as error:
        BranchManager(tmp_path).ensure_ready()

    assert r"untracked: generated-\\xff.txt" in str(error.value)
    assert all(command["encoding"] == "utf-8" for command in commands)
    assert all(command["errors"] == "backslashreplace" for command in commands)


def test_ensure_ready_ignores_gitignored_generated_files(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("artifacts/\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitignore"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: ignore artifacts"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "ruff.sarif").write_text("{}\n", encoding="utf-8")

    BranchManager(tmp_path).ensure_ready()


def test_ensure_ready_allows_only_configured_untracked_runtime_outputs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _init_git_repo(tmp_path)
    caplog.set_level(logging.INFO)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (tmp_path / ".zeroone-ops-state.json").write_text("{}\n", encoding="utf-8")
    (artifacts / "ruff.sarif").write_text("{}\n", encoding="utf-8")

    manager = BranchManager(
        tmp_path,
        runtime_workspace_policy=RuntimeWorkspacePolicy(
            frozenset({".zeroone-ops-state.json", "artifacts/ruff.sarif"})
        ),
    )

    manager.ensure_ready()

    assert "ignored configured runtime workspace output(s)" in caplog.text
    assert ".zeroone-ops-state.json" in caplog.text
    assert "artifacts/ruff.sarif" in caplog.text


def test_ensure_ready_rejects_unconfigured_runtime_artifact(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "semgrep.sarif").write_text("{}\n", encoding="utf-8")

    with pytest.raises(BranchManagerError) as error:
        BranchManager(
            tmp_path,
            runtime_workspace_policy=RuntimeWorkspacePolicy(frozenset({"artifacts/ruff.sarif"})),
        ).ensure_ready()

    assert "- untracked: artifacts/semgrep.sarif" in str(error.value)


def test_ensure_ready_rejects_modified_configured_runtime_output(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    state_path = tmp_path / ".zeroone-ops-state.json"
    state_path.write_text("{}\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", state_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: add state fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    state_path.write_text('{"changed": true}\n', encoding="utf-8")

    with pytest.raises(BranchManagerError) as error:
        BranchManager(
            tmp_path,
            runtime_workspace_policy=RuntimeWorkspacePolicy(frozenset({state_path.name})),
        ).ensure_ready()

    assert "- modified: .zeroone-ops-state.json" in str(error.value)


def test_parse_porcelain_status_categorizes_workspace_changes() -> None:
    changes = parse_porcelain_status(
        " M path with spaces.py\0"
        "M  staged.py\0"
        "?? artifacts/mypy.sarif\0"
        "R  renamed.py\0original.py\0"
        "C  copied.py\0source.py\0"
    )

    assert [(change.category, change.path, change.previous_path) for change in changes] == [
        ("modified", "path with spaces.py", None),
        ("staged modification", "staged.py", None),
        ("untracked", "artifacts/mypy.sarif", None),
        ("renamed", "renamed.py", "original.py"),
        ("copied", "copied.py", "source.py"),
    ]


def test_dirty_workspace_message_is_bounded_and_markdown_safe() -> None:
    changes = parse_porcelain_status("".join(f"?? generated-{index}.txt\0" for index in range(11)))

    message = _format_dirty_workspace_message(changes)

    assert "- untracked: generated-0.txt" in message
    assert "generated-9.txt" in message
    assert "... and 1 more paths." in message

    unsafe_message = _format_dirty_workspace_message(
        parse_porcelain_status("?? unsafe_[name]\\path\n.txt\0")
    )

    assert "unsafe\\_\\[name\\]\\\\path\\n.txt" in unsafe_message


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
