"""Compose production sync, intake, and execution over offline transport."""

from dataclasses import dataclass

import httpx
import pytest

from zeroone_ops.models.config import (
    AppConfig,
    GitHubConfig,
    GitHubConnectionConfig,
    GitLabConfig,
    GitLabConnectionConfig,
    RemediationConfig,
)
from zeroone_ops.models.finding import NormalizedFinding, RemediationContext
from zeroone_ops.models.finding_sync import FindingSyncResult
from zeroone_ops.models.policy import PolicySeverityStateEntry, PolicyState
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.providers.github_client import GitHubClient
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.providers.gitlab_client import GitLabClient
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient
from zeroone_ops.services.control_plane.work_items.github_finding_sync_service import (
    GitHubFindingSyncService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_parser import (
    GitHubWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_finding_sync_service import (
    GitLabFindingSyncService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_parser import (
    GitLabWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.remediation.change_request_publisher import (
    GitHubRemediationChangeRequestPublisher,
    GitLabRemediationChangeRequestPublisher,
)
from zeroone_ops.services.remediation.control_plane import (
    GitHubRemediationControlPlane,
    GitLabRemediationControlPlane,
)
from zeroone_ops.services.remediation.execution_service import ExecutionService
from zeroone_ops.services.remediation.github_remediation_runner import GitHubRemediationRunner
from zeroone_ops.services.remediation.gitlab_remediation_runner import GitLabRemediationRunner
from zeroone_ops.services.remediation.work_item_remediation_runner import WorkItemRemediationRunner
from zeroone_ops.services.shared.run_state_service import RunStateService
from zeroone_ops.services.shared.state_store import StateStore

from .provider_api import REPOSITORY_SCOPE, ScenarioProviderAPI
from .repository import TARGET_PATH, ScenarioRepository
from .scripted_model import ScriptedModel

SCOPE = REPOSITORY_SCOPE
RUN_ID = "scenario-execution"


@dataclass(frozen=True)
class ScenarioHarness:
    """Expose real workflows and inspect state only through provider parsers."""

    api: ScenarioProviderAPI
    work_items: GitHubWorkItemService | GitLabWorkItemService
    policy: PolicyState
    findings: list[NormalizedFinding]
    runner: WorkItemRemediationRunner
    runs: RunStateService
    engine: ExecutionService
    model: ScriptedModel

    def sync(self, run_id: str) -> FindingSyncResult:
        """Run public provider sync against the same normalized inventory."""
        options = dict(
            findings=self.findings,
            policy_state=self.policy,
            managed_source_ids={"ruff-sarif"},
            max_active_work_items=1,
            run_id=run_id,
        )
        if isinstance(self.work_items, GitHubWorkItemService):
            return GitHubFindingSyncService(work_item_service=self.work_items).sync(
                repository_id=SCOPE, **options
            )
        return GitLabFindingSyncService(work_item_service=self.work_items).sync(
            project_id=SCOPE, **options
        )

    def parse(self, payload: dict[str, object]) -> WorkItemState:
        """Read authoritative machine state with the production provider parser."""
        if self.api.platform == "github":
            state = GitHubWorkItemParser().parse_work_item_state(str(payload["body"]))
        else:
            state = GitLabWorkItemParser().parse_work_item_state(str(payload["description"]))
        assert state is not None
        return state

    def work_item(self) -> WorkItemState:
        """Read the single expected issue without retaining a domain-state cache."""
        assert len(self.api.issues) == 1
        return self.parse(next(iter(self.api.issues.values())))


def compose_scenario(
    repository: ScenarioRepository,
    api: ScenarioProviderAPI,
    http: httpx.Client,
    replacements: tuple[str | None, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> ScenarioHarness:
    """Inject only model construction and provider transport into production services."""
    config = AppConfig(
        platform=api.platform,
        execution_mode="ci",
        base_branch="main",
        github=GitHubConfig(),
        gitlab=GitLabConfig(),
        remediation=RemediationConfig(
            target_branch="main",
            validation_commands=[repository.validation_command],
            validation_feedback_enabled=True,
            max_retry_count=1,
        ),
    )
    policy = PolicyState(
        severity_policy=[PolicySeverityStateEntry(severity="medium", enabled=True)]
    )
    store = StateStore(
        repository.root / config.state.path,
        base_branch="main",
        gitlab_project_id=SCOPE if api.platform == "gitlab" else None,
        sonarqube_project_key=None,
    )
    runs = RunStateService(config, store, store.load())
    if api.platform == "github":
        connection = GitHubConnectionConfig(
            api_url="https://provider.invalid",
            server_url="https://provider.invalid",
            token="offline-test-token",
            repository=SCOPE,
        )
        work_items = GitHubWorkItemService(GitHubWorkItemClient(connection, http_client=http))
        control_plane = GitHubRemediationControlPlane(
            work_item_service=work_items, repository_id=SCOPE
        )
        publisher = GitHubRemediationChangeRequestPublisher(
            GitHubClient(connection, http_client=http)
        )
        runner_type = GitHubRemediationRunner
        scope_arguments = {"repository_id": SCOPE}
    else:
        connection = GitLabConnectionConfig(
            url="https://provider.invalid", token="offline-test-token", project_id=SCOPE
        )
        work_items = GitLabWorkItemService(GitLabWorkItemClient(connection, http_client=http))
        control_plane = GitLabRemediationControlPlane(
            work_item_service=work_items, project_id=SCOPE
        )
        publisher = GitLabRemediationChangeRequestPublisher(
            GitLabClient(connection, http_client=http)
        )
        runner_type = GitLabRemediationRunner
        scope_arguments = {"project_id": SCOPE}

    engine = ExecutionService(repository.root, config, remediation_control_plane=control_plane)
    engine.analysis_service.validator.timeout_seconds = 20
    engine.publish_service.change_request_publisher = publisher
    runner = runner_type(
        repo_root=repository.root,
        config=config,
        work_item_service=work_items,
        execution_service=engine,
        remediation_control_plane=control_plane,
        run_state_service=runs,
        load_batch_policy=lambda: policy,
        **scope_arguments,
    )

    def verify_claim(target: RemediationExecutionTarget) -> None:
        current = harness.work_item()
        assert current.status == "in_progress"
        assert current.claim is not None and current.claim.run_id == RUN_ID
        assert current.batch_attempt is not None
        assert current.batch_attempt == target.batch_attempt
        assert target.batch_attempt.run_id == RUN_ID

    model = ScriptedModel(repository.source, replacements, verify_claim)
    monkeypatch.setattr(engine.analysis_service, "_build_llm_client", lambda: model)
    findings = [
        NormalizedFinding(
            finding_id=f"unused-{name}",
            source_id="ruff-sarif",
            severity="medium",
            title="Unused import",
            summary=f"{name} imported but unused",
            repository_path=TARGET_PATH,
            line_start=line,
            remediation_context=RemediationContext(
                category="static_analysis_fix", diagnostic_code="F401"
            ),
        )
        for line, name in enumerate(("os", "sys"), start=1)
    ]
    harness = ScenarioHarness(api, work_items, policy, findings, runner, runs, engine, model)
    return harness
