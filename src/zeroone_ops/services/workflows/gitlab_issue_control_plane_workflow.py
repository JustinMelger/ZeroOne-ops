"""GitLab issue-mode control-plane workflow composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.state import RunStatus
from zeroone_ops.services.shared.run_state_service import RunSummary


class GitLabIssueControlPlaneWorkflow:
    """Run policy, recovery, and remediation in the required GitLab order."""

    def __init__(
        self,
        *,
        run_policy: Callable[..., RunSummary],
        run_recovery: Callable[..., RunSummary],
        run_remediation: Callable[..., RunSummary],
        publish_overview: Callable[[], str],
    ) -> None:
        """Initialize the explicit workflow dependencies at the composition boundary."""
        self._run_policy = run_policy
        self._run_recovery = run_recovery
        self._run_remediation = run_remediation
        self._publish_overview = publish_overview

    def run(self, *, config: AppConfig, dry_run: bool) -> RunSummary:
        """Run the combined operation and publish one final derived overview."""
        policy_summary = self._run_policy(
            dry_run=dry_run,
            publish_operational_summary=False,
        )
        if policy_summary.status != RunStatus.SYNCED:
            return policy_summary

        recovery_summary = self._run_recovery(
            dry_run=dry_run,
            publish_operational_summary=False,
        )
        if recovery_summary.status != RunStatus.SYNCED:
            return recovery_summary

        remediation_summary = self._run_remediation(
            dry_run=dry_run,
            publish_operational_summary=False,
        )
        if dry_run or config.dry_run:
            return remediation_summary

        return replace(
            remediation_summary,
            message=remediation_summary.message + self._publish_overview(),
        )
