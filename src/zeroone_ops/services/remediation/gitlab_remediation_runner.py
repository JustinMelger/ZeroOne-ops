"""GitLab-local composition for shared work-item remediation."""

from __future__ import annotations

from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.services.control_plane.work_items.gitlab_remediation_intake_service import (
    GitLabRemediationIntakeResult,
    GitLabRemediationIntakeService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.remediation.control_plane import (
    RemediationControlPlane,
    build_remediation_control_plane,
)
from zeroone_ops.services.remediation.execution_service import ExecutionService
from zeroone_ops.services.remediation.recovery.publication_retry_service import (
    PublicationRetryService,
)
from zeroone_ops.services.remediation.work_item_remediation_runner import (
    WorkItemRemediationRunner,
)
from zeroone_ops.services.shared.run_state_service import RunStateService


class GitLabRemediationRunner(WorkItemRemediationRunner):
    """Compose shared work-item remediation with GitLab intake and projection."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        project_id: str,
        work_item_service: GitLabWorkItemService,
        run_state_service: RunStateService,
        execution_service: ExecutionService | None = None,
        remediation_control_plane: RemediationControlPlane | None = None,
        publication_retry_service: PublicationRetryService | None = None,
    ) -> None:
        """Initialize GitLab-specific work-item remediation composition."""
        gitlab_config = config.require_gitlab_config(reason="GitLab work-item remediation")
        if gitlab_config.control_plane_mode != "issues":
            raise ValueError(
                "GitLab work-item remediation requires gitlab.control_plane_mode='issues'."
            )
        self.project_id = project_id
        self.work_item_service = work_item_service
        control_plane = remediation_control_plane or build_remediation_control_plane(
            config,
            gitlab_work_item_service=work_item_service,
            gitlab_project_id=project_id,
        )
        super().__init__(
            repo_root=repo_root,
            config=config,
            run_state_service=run_state_service,
            execution_service=execution_service
            or ExecutionService(
                repo_root=repo_root,
                config=config,
                remediation_control_plane=control_plane,
            ),
            remediation_control_plane=control_plane,
            publication_retry_service=publication_retry_service,
        )

    def _select_and_claim(
        self,
        *,
        persist: bool,
        run_id: str,
    ) -> GitLabRemediationIntakeResult:
        """Select and claim one eligible GitLab work item."""
        return GitLabRemediationIntakeService(
            work_item_service=self.work_item_service
        ).select_and_claim(
            project_id=self.project_id,
            persist=persist,
            run_id=run_id,
        )
