from pathlib import Path

from zeroone_ops.models.config import AppConfig, GitLabConfig, SarifArtifactConfig, SarifConfig
from zeroone_ops.services.shared.runtime_workspace import (
    RuntimeWorkspacePolicy,
    parse_porcelain_status,
)


def _build_config(*, state_path: Path, artifact_path: Path, solution_path: Path) -> AppConfig:
    return AppConfig(
        base_branch="main",
        gitlab=GitLabConfig(target_branch="main"),
        state={"path": state_path},
        sarif=SarifConfig(
            artifacts=[SarifArtifactConfig(path=artifact_path, source_id="ruff-sarif")]
        ),
        openai_solution_output_path=solution_path,
    )


def test_runtime_workspace_policy_allows_exact_configured_untracked_outputs(tmp_path: Path) -> None:
    policy = RuntimeWorkspacePolicy.from_config(
        config=_build_config(
            state_path=Path(".zeroone-ops-state.json"),
            artifact_path=Path("artifacts/ruff.sarif"),
            solution_path=Path("artifacts/openai-solution.json"),
        ),
        repo_root=tmp_path,
    )

    blocking, ignored = policy.split_changes(
        parse_porcelain_status(
            "?? .zeroone-ops-state.json\0"
            "?? artifacts/ruff.sarif\0"
            "?? artifacts/openai-solution.json\0"
            "?? artifacts/other.sarif\0"
        )
    )

    assert [change.path for change in ignored] == [
        ".zeroone-ops-state.json",
        "artifacts/ruff.sarif",
        "artifacts/openai-solution.json",
    ]
    assert [(change.category, change.path) for change in blocking] == [
        ("untracked", "artifacts/other.sarif"),
    ]


def test_runtime_workspace_policy_keeps_non_untracked_configured_paths_blocking(
    tmp_path: Path,
) -> None:
    policy = RuntimeWorkspacePolicy(frozenset({"artifacts/ruff.sarif"}))

    blocking, ignored = policy.split_changes(
        parse_porcelain_status(
            " M artifacts/ruff.sarif\0"
            "M  artifacts/ruff.sarif\0"
            "D  artifacts/ruff.sarif\0"
            "R  artifacts/ruff.sarif\0previous.sarif\0"
            "C  artifacts/ruff.sarif\0source.sarif\0"
            "UU artifacts/ruff.sarif\0"
        )
    )

    assert ignored == []
    assert [(change.category, change.path) for change in blocking] == [
        ("modified", "artifacts/ruff.sarif"),
        ("staged modification", "artifacts/ruff.sarif"),
        ("staged deletion", "artifacts/ruff.sarif"),
        ("renamed", "artifacts/ruff.sarif"),
        ("copied", "artifacts/ruff.sarif"),
        ("unmerged", "artifacts/ruff.sarif"),
    ]


def test_runtime_workspace_policy_rejects_absolute_and_escaping_configured_paths(
    tmp_path: Path,
) -> None:
    policy = RuntimeWorkspacePolicy.from_config(
        config=_build_config(
            state_path=tmp_path / ".zeroone-ops-state.json",
            artifact_path=Path("../artifacts/ruff.sarif"),
            solution_path=Path("artifacts/openai-solution.json"),
        ),
        repo_root=tmp_path,
    )

    blocking, ignored = policy.split_changes(
        parse_porcelain_status(
            "?? .zeroone-ops-state.json\0"
            "?? artifacts/ruff.sarif\0"
            "?? artifacts/openai-solution.json\0"
        )
    )

    assert [change.path for change in ignored] == ["artifacts/openai-solution.json"]
    assert [change.path for change in blocking] == [
        ".zeroone-ops-state.json",
        "artifacts/ruff.sarif",
    ]
