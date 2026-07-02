from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    GitLabConnectionConfig,
    RemediationConfig,
)
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.services.remediation.publish_service import PublishService


def build_config() -> AppConfig:
    return AppConfig(
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


def build_issue() -> RemediationExecutionTarget:
    return RemediationExecutionTarget(
        item_id="FIXTURE-1",
        source_type="sonarqube",
        source_ref="FIXTURE-1",
        title="python:S2259 in src/service.py",
        status="OPEN",
        message="Fixture issue",
        file_path="src/service.py",
        line=1,
        rule_id="python:S2259",
        severity="MAJOR",
        issue_type="BUG",
        component="sample-project:src/service.py",
        project="sample-project",
    )


class StubBranchManager:
    def push_current_branch(self, *, remote_name: str = "origin") -> str:
        del remote_name
        return "zeroone-ops/fix"


def test_publish_service_builds_deterministic_description() -> None:
    service = PublishService(config=build_config(), branch_manager=StubBranchManager())  # type: ignore[arg-type]

    description = service.build_change_request_description(
        selected_issue=build_issue(),
        change_summary="summary",
    )

    assert description == "\n".join(
        [
            "## Summary",
            "summary",
            "",
            "## Remediation Target",
            "- Source: `SonarQube`",
            "- Issue key: `FIXTURE-1`",
            "- Rule: `python:S2259`",
            "- Severity: `MAJOR`",
            "- Type: `BUG`",
            "- File: `src/service.py`",
            "- Line: `1`",
            "- Message: Fixture issue",
            "",
            "## Notes",
            "- Diff was rendered by the bot from a structured edit proposal.",
        ]
    )


def test_publish_service_uses_generic_profile_for_unknown_source() -> None:
    service = PublishService(config=build_config(), branch_manager=StubBranchManager())  # type: ignore[arg-type]

    description = service.build_change_request_description(
        selected_issue=RemediationExecutionTarget(
            item_id="pipeline:1",
            source_type="pipeline_failure",
            source_ref="job-1",
            title="pytest failed in src/service.py",
            status="open",
            message="Test suite is failing.",
            file_path="src/service.py",
        ),
        change_summary="summary",
    )

    assert "## Remediation Target" in description
    assert "- Source: `Remediation`" in description
    assert "- Item reference: `job-1`" in description


def test_publish_service_builds_conventional_commit_change_request_title() -> None:
    service = PublishService(config=build_config(), branch_manager=StubBranchManager())  # type: ignore[arg-type]

    title = service.build_change_request_title(
        selected_issue=build_issue(),
        proposed_title="patch service please",
    )

    assert title == "fix: remediate python:S2259 in service.py"


def test_publish_service_uses_pushed_branch_consistently(monkeypatch) -> None:
    service = PublishService(config=build_config(), branch_manager=StubBranchManager())  # type: ignore[arg-type]
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        "zeroone_ops.services.remediation.publish_service.load_gitlab_connection_config",
        lambda: GitLabConnectionConfig(
            url="https://gitlab.example.com",
            token="token",
            project_id="group/project",
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.publish_service.ChangeRequestService.find_open",
        lambda self, project_id, source_branch, target_branch: None,
    )

    def capture_create(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        labels: list[str],
        assignee_id: int | None = None,
    ) -> ChangeRequestInfo:
        del self, project_id, target_branch, title, description, labels, assignee_id
        captured["source_branch"] = source_branch
        return ChangeRequestInfo(
            iid=17,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
            title="fix: remediate python:S2259 in service.py",
        )

    monkeypatch.setattr(
        "zeroone_ops.services.remediation.publish_service.ChangeRequestService.create",
        capture_create,
    )

    result = service.publish(
        selected_issue=build_issue(),
        branch_name="caller-branch-name",
        mr_title="ignored",
        mr_description="summary",
    )

    assert captured["source_branch"] == "zeroone-ops/fix"
    assert result.branch_name == "zeroone-ops/fix"


def test_publish_service_assigns_created_merge_request_by_configured_username(
    monkeypatch,
) -> None:
    service = PublishService(
        config=AppConfig(
            execution_mode="ci",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                bootstrap_severities=["MAJOR"],
                analysis=AnalysisConfig(),
            ),
            gitlab=GitLabConfig(
                target_branch="main",
                labels=["zeroone-ops"],
                merge_request_assignee_username="justin",
            ),
        ),
        branch_manager=StubBranchManager(),  # type: ignore[arg-type]
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "zeroone_ops.services.remediation.publish_service.load_gitlab_connection_config",
        lambda: GitLabConnectionConfig(
            url="https://gitlab.example.com",
            token="token",
            project_id="group/project",
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.publish_service.ChangeRequestService.find_open",
        lambda self, project_id, source_branch, target_branch: None,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.publish_service.GitLabClient.find_user_id_by_username",
        lambda self, username: 42 if username == "justin" else 0,
    )

    def capture_create(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        labels: list[str],
        assignee_id: int | None = None,
    ) -> ChangeRequestInfo:
        del self, project_id, source_branch, target_branch, title, description, labels
        captured["assignee_id"] = assignee_id
        return ChangeRequestInfo(
            iid=17,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
            title="fix: remediate python:S2259 in service.py",
        )

    monkeypatch.setattr(
        "zeroone_ops.services.remediation.publish_service.ChangeRequestService.create",
        capture_create,
    )

    result = service.publish(
        selected_issue=build_issue(),
        branch_name="caller-branch-name",
        mr_title="ignored",
        mr_description="summary",
    )

    assert captured["assignee_id"] == 42
    assert result.change_request_action == "created"


def test_publish_service_assigns_reused_merge_request_by_configured_username(
    monkeypatch,
) -> None:
    service = PublishService(
        config=AppConfig(
            execution_mode="ci",
            base_branch="main",
            validation_commands=[],
            approval=ApprovalConfig(),
            remediation=RemediationConfig(
                bootstrap_severities=["MAJOR"],
                analysis=AnalysisConfig(),
            ),
            gitlab=GitLabConfig(
                target_branch="main",
                labels=["zeroone-ops"],
                merge_request_assignee_username="justin",
            ),
        ),
        branch_manager=StubBranchManager(),  # type: ignore[arg-type]
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "zeroone_ops.services.remediation.publish_service.load_gitlab_connection_config",
        lambda: GitLabConnectionConfig(
            url="https://gitlab.example.com",
            token="token",
            project_id="group/project",
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.publish_service.GitLabClient.find_user_id_by_username",
        lambda self, username: 42 if username == "justin" else 0,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.publish_service.ChangeRequestService.find_open",
        lambda self, project_id, source_branch, target_branch: ChangeRequestInfo(
            iid=17,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
            title="fix: remediate python:S2259 in service.py",
        ),
    )

    def capture_assign(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        assignee_id: int,
    ) -> None:
        del self, project_id
        captured["merge_request_iid"] = merge_request_iid
        captured["assignee_id"] = assignee_id

    monkeypatch.setattr(
        "zeroone_ops.services.remediation.publish_service.ChangeRequestService.assign",
        capture_assign,
    )

    result = service.publish(
        selected_issue=build_issue(),
        branch_name="caller-branch-name",
        mr_title="ignored",
        mr_description="summary",
    )

    assert captured["merge_request_iid"] == 17
    assert captured["assignee_id"] == 42
    assert result.change_request_action == "reused"
