from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitHubConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.services.control_plane.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.remediation.control_plane import (
    GitHubRemediationControlPlane,
    NoOpRemediationControlPlane,
    build_remediation_control_plane,
)


class DummyGitHubWorkItemClient:
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
