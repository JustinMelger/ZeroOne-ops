"""GitHub-local composition for shared work-item remediation."""

from __future__ import annotations

import os
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.services.control_plane.work_items.github_remediation_intake_service import (
    GitHubRemediationIntakeResult,
    GitHubRemediationIntakeService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
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


class GitHubRemediationRunner(WorkItemRemediationRunner):
    """Compose shared work-item remediation with GitHub intake and CI traceability."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        repository_id: str,
        work_item_service: GitHubWorkItemService,
        run_state_service: RunStateService,
        execution_service: ExecutionService | None = None,
        remediation_control_plane: RemediationControlPlane | None = None,
        publication_retry_service: PublicationRetryService | None = None,
    ) -> None:
        """Initialize GitHub-specific work-item remediation composition."""
        self.repository_id = repository_id
        self.work_item_service = work_item_service
        super().__init__(
            repo_root=repo_root,
            config=config,
            run_state_service=run_state_service,
            execution_service=execution_service,
            remediation_control_plane=(
                remediation_control_plane
                or build_remediation_control_plane(
                    config,
                    github_work_item_service=work_item_service,
                    github_repository_id=repository_id,
                )
            ),
            publication_retry_service=publication_retry_service,
            execution_url_builder=_github_actions_run_url,
        )

    def _select_and_claim(
        self,
        *,
        persist: bool,
        run_id: str,
    ) -> GitHubRemediationIntakeResult:
        """Select and claim one eligible GitHub work item."""
        return GitHubRemediationIntakeService(
            work_item_service=self.work_item_service
        ).select_and_claim(
            repository_id=self.repository_id,
            persist=persist,
            run_id=run_id,
        )


def _github_actions_run_url() -> str | None:
    """Return the current GitHub Actions run URL when CI exposes its identity."""
    server_url = os.environ.get("GITHUB_SERVER_URL")
    repository = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not server_url or not repository or not run_id:
        return None
    return f"{server_url.rstrip('/')}/{repository}/actions/runs/{run_id}"
