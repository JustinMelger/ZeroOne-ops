from pathlib import Path

from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.services.review.pipeline.review_runner import ReviewRunner


def test_gitlab_issue_mode_skips_legacy_dashboard_review_mirror(tmp_path: Path) -> None:
    runner = ReviewRunner(
        repo_root=tmp_path,
        config=AppConfig(
            execution_mode="ci",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                target_branch="main",
                analysis=AnalysisConfig(),
            ),
            gitlab=GitLabConfig(
                control_plane_mode="issues",
                target_branch="main",
                labels=[],
            ),
        ),
        review_client=object(),  # type: ignore[arg-type]
        dashboard_client=object(),  # type: ignore[arg-type]
        review_state_service=object(),  # type: ignore[arg-type]
    )

    assert runner._build_dashboard_updater() is None
