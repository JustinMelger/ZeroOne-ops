from pathlib import Path

import pytest

from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitHubConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.remediation.control_plane import (
    GitHubRemediationControlPlane,
    GitLabRemediationControlPlane,
    NoOpRemediationControlPlane,
    build_remediation_control_plane,
)
from zeroone_ops.services.remediation.gitlab_remediation_runner import (
    GitLabRemediationRunner,
)


class DummyGitHubWorkItemClient:
    pass


class DummyGitLabWorkItemClient:
    pass


def test_build_remediation_control_plane_returns_noop_for_gitlab() -> None:
    control_plane = build_remediation_control_plane(
        AppConfig(
            execution_mode="ci",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                bootstrap_severities=["MAJOR"],
                analysis=AnalysisConfig(),
            ),
            gitlab=GitLabConfig(target_branch="main", labels=["zeroone-ops"]),
        )
    )

    assert isinstance(control_plane, NoOpRemediationControlPlane)


def test_build_remediation_control_plane_returns_noop_for_gitlab_dashboard_mode() -> None:
    work_item_service = GitLabWorkItemService(DummyGitLabWorkItemClient())  # type: ignore[arg-type]

    control_plane = build_remediation_control_plane(
        AppConfig(
            execution_mode="ci",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                target_branch="main",
                bootstrap_severities=["MAJOR"],
                analysis=AnalysisConfig(),
            ),
            gitlab=GitLabConfig(target_branch="main", labels=["zeroone-ops"]),
        ),
        gitlab_work_item_service=work_item_service,
        gitlab_project_id="group/project",
    )

    assert isinstance(control_plane, NoOpRemediationControlPlane)


def test_build_remediation_control_plane_returns_github_adapter_with_override() -> None:
    work_item_service = GitHubWorkItemService(DummyGitHubWorkItemClient())  # type: ignore[arg-type]

    control_plane = build_remediation_control_plane(
        AppConfig(
            execution_mode="ci",
            platform="github",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                target_branch="main",
                bootstrap_severities=["MAJOR"],
                analysis=AnalysisConfig(),
            ),
            github=GitHubConfig(labels=["zeroone-ops"]),
        ),
        github_work_item_service=work_item_service,
        github_repository_id="octo-org/octo-repo",
    )

    assert isinstance(control_plane, GitHubRemediationControlPlane)
    assert control_plane.work_item_service is work_item_service
    assert control_plane.repository_id == "octo-org/octo-repo"


def test_build_remediation_control_plane_returns_gitlab_adapter_in_issue_mode() -> None:
    work_item_service = GitLabWorkItemService(DummyGitLabWorkItemClient())  # type: ignore[arg-type]

    control_plane = build_remediation_control_plane(
        AppConfig(
            execution_mode="ci",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                target_branch="main",
                bootstrap_severities=["MAJOR"],
                analysis=AnalysisConfig(),
            ),
            gitlab=GitLabConfig(
                control_plane_mode="issues",
                target_branch="main",
                labels=["zeroone-ops"],
            ),
        ),
        gitlab_work_item_service=work_item_service,
        gitlab_project_id="group/project",
    )

    assert isinstance(control_plane, GitLabRemediationControlPlane)
    assert control_plane.work_item_service is work_item_service
    assert control_plane.project_id == "group/project"


def test_gitlab_runner_reuses_one_control_plane_for_execution_and_publication(
    tmp_path: Path,
) -> None:
    config = AppConfig(
        execution_mode="ci",
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            target_branch="main",
            bootstrap_severities=["MAJOR"],
            analysis=AnalysisConfig(),
        ),
        gitlab=GitLabConfig(
            control_plane_mode="issues",
            target_branch="main",
            labels=["zeroone-ops"],
        ),
    )
    work_item_service = GitLabWorkItemService(DummyGitLabWorkItemClient())  # type: ignore[arg-type]
    runner = GitLabRemediationRunner(
        repo_root=tmp_path,
        config=config,
        project_id="group/project",
        work_item_service=work_item_service,
        run_state_service=object(),  # type: ignore[arg-type]
    )

    assert isinstance(runner.remediation_control_plane, GitLabRemediationControlPlane)
    assert (
        runner.execution_service.publish_service._remediation_control_plane_override
        is runner.remediation_control_plane
    )


def test_gitlab_runner_rejects_dashboard_mode(tmp_path: Path) -> None:
    config = AppConfig(
        execution_mode="ci",
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            target_branch="main",
            bootstrap_severities=["MAJOR"],
            analysis=AnalysisConfig(),
        ),
        gitlab=GitLabConfig(target_branch="main", labels=["zeroone-ops"]),
    )
    work_item_service = GitLabWorkItemService(DummyGitLabWorkItemClient())  # type: ignore[arg-type]

    with pytest.raises(
        ValueError,
        match="GitLab work-item remediation requires gitlab.control_plane_mode='issues'",
    ):
        GitLabRemediationRunner(
            repo_root=tmp_path,
            config=config,
            project_id="group/project",
            work_item_service=work_item_service,
            run_state_service=object(),  # type: ignore[arg-type]
        )
