from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from zeroone_ops.models.batch_execution import BatchAnalysisCoverage, BatchAttemptEvidence
from zeroone_ops.models.config import (
    AppConfig,
    GitHubConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.models.finding_batch_snapshot import BatchFindingSnapshot
from zeroone_ops.models.review import ChangeRequestReviewContext
from zeroone_ops.models.work_item import ChangeRequestRef, WorkItemSourceRef, WorkItemState
from zeroone_ops.services.review.pipeline import review_runner
from zeroone_ops.services.review.pipeline.review_runner import ReviewRunner
from zeroone_ops.settings import SettingsError


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("lookup", ["linked", "absent", "wrong_url", "failure"])
@pytest.mark.parametrize("with_batch", [False, True])
def test_verified_notice_link_does_not_require_semantic_safety(
    tmp_path, monkeypatch, platform, lookup, with_batch
):
    context = ChangeRequestReviewContext(
        change_request_number=9,
        title="Remediation",
        source_branch="remediation",
        target_branch="main",
        head_sha="sha",
        web_url="https://example.com/pr/9",
        description="Tracking work item: https://untrusted.example/issues/1",
    )
    work_item = WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="in_progress",
        summary="Fix",
        source=WorkItemSourceRef(source="ruff", source_item_key="1", repository_scope="org/repo"),
        linked_change_request=ChangeRequestRef(
            number=9,
            web_url="https://other.example/pr/9" if lookup == "wrong_url" else context.web_url,
        ),
    )
    if with_batch:
        identity = uuid4().hex
        member = BatchFindingSnapshot(
            finding_id="member",
            source_id="ruff",
            severity="medium",
            title="Unused import",
            summary="Remove import",
            repository_path="src/app.py",
            line_start=1,
            remediation_context={"category": "static_analysis_fix", "diagnostic_code": "F401"},
        )
        attempt = BatchAttemptEvidence(
            batch_id=f"work-{identity}",
            attempt_number=1,
            run_id="original-execution",
            members=(member,),
            observation_run_ids=("scan",),
            coverage=BatchAnalysisCoverage(addressable_ids=("member",)),
        )
        work_item = WorkItemState.model_validate(
            work_item.model_dump()
            | {
                "work_item_id": f"work-{identity}",
                "file_path": "src/app.py",
                "source": {
                    "source": "ruff",
                    "source_item_key": f"batch-v1:{identity}",
                    "repository_scope": "org/repo",
                },
                "remediation_context": {
                    "category": "static_analysis_fix",
                    "diagnostic_code": "F401",
                },
                "batch": {
                    "group": {
                        "repository_scope": "org/repo",
                        "file_path": "src/app.py",
                        "source_id": "ruff",
                        "rule_id": "F401",
                    },
                    "members": [member],
                    "observations": [
                        {
                            "finding_id": "member",
                            "last_confirmed_presence": "detected",
                            "freshness": "current",
                            "sync_run_id": "scan",
                            "observed_at": datetime(2026, 10, 19, tzinfo=UTC),
                        }
                    ],
                },
                "batch_attempt": attempt,
            }
        )
    result = (
        None
        if lookup == "absent"
        else SimpleNamespace(
            work_item=work_item, issue=SimpleNamespace(web_url="https://example.com/issues/12")
        )
    )
    service = Mock()
    service.find_open_work_item_by_change_request.return_value = result
    if lookup == "failure":
        service.find_open_work_item_by_change_request.side_effect = SettingsError("Unavailable")
    name = "GitHub" if platform == "github" else "GitLab"
    monkeypatch.setattr(review_runner, f"{name}WorkItemService", lambda client: service)
    monkeypatch.setattr(review_runner, f"{name}WorkItemClient", lambda config: object())
    monkeypatch.setattr(review_runner, f"load_{platform}_connection_config", lambda: object())
    runner = ReviewRunner(
        repo_root=tmp_path,
        config=AppConfig(
            remediation=RemediationConfig(target_branch="main"),
            platform=platform,
            base_branch="main",
            github=GitHubConfig(),
            gitlab=GitLabConfig(),
        ),
        review_client=object(),
        review_state_service=object(),
    )
    updated = runner._with_verified_remediation_context(repository_id="org/repo", context=context)
    if lookup == "linked":
        assert updated.remediation_context.verified_work_item_url == "https://example.com/issues/12"
        assert updated.remediation_context.semantic_safety is None
        assert updated.remediation_context.batch_attempt == work_item.batch_attempt
    else:
        assert updated.remediation_context is None
