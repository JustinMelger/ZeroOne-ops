from pathlib import Path

from zeroone_ops.models.analysis import (
    CodeContextSnippet,
    IssueContext,
    PatchProposal,
    ValidationCommandResult,
    ValidationResult,
)
from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.services.remediation.fix_generator import FixGenerator
from zeroone_ops.services.remediation.patch_applier import (
    PatchApplier,
    PatchApplyError,
)
from zeroone_ops.services.remediation.patch_execution_service import (
    PatchExecutionService,
)
from zeroone_ops.services.remediation.validator import Validator
from zeroone_ops.services.shared.workspace_snapshot import WorkspaceSnapshotService


class StubFixGenerator(FixGenerator):
    def __init__(self) -> None:
        pass


def build_config(
    *,
    validation_setup_commands: list[str] | None = None,
    validation_commands: list[str] | None = None,
    max_retry_count: int = 0,
) -> AppConfig:
    return AppConfig(
        base_branch="main",
        validation_setup_commands=validation_setup_commands or [],
        validation_commands=validation_commands or [],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            bootstrap_severities=["LOW"],
            max_retry_count=max_retry_count,
            analysis=AnalysisConfig(),
        ),
        gitlab=GitLabConfig(target_branch="main"),
    )


def build_issue() -> RemediationExecutionTarget:
    return RemediationExecutionTarget(
        item_id="AX1",
        source_type="sonarqube",
        source_ref="AX1",
        title="python:S1125 in src/service.py",
        status="OPEN",
        message="Issue",
        file_path="src/service.py",
        line=1,
        rule_id="python:S1125",
        severity="LOW",
        issue_type="BUG",
        component="component",
        project="project",
    )


def build_context() -> IssueContext:
    return IssueContext(
        issue_key="AX1",
        file_path="src/service.py",
        line=1,
        file_size_bytes=10,
        snippet=CodeContextSnippet(start_line=1, end_line=1, content="1: value = 1"),
        full_file_included=True,
        truncated=False,
    )


def build_patch() -> PatchProposal:
    return PatchProposal(
        issue_key="AX1",
        files_touched=["src/service.py"],
        unified_diff="diff --git a/src/service.py b/src/service.py\n",
        commit_message="fix(sonar): update service [AX1]",
        change_request_title="fix: update service",
        change_request_description="summary",
    )


def test_patch_execution_service_restores_files_on_patch_apply_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "src").mkdir()
    target_file = tmp_path / "src" / "service.py"
    target_file.write_text("value = 1\n", encoding="utf-8")

    service = PatchExecutionService(
        config=build_config(),
        patch_applier=PatchApplier(tmp_path),
        validator=Validator(tmp_path),
        workspace_snapshot_service=WorkspaceSnapshotService(tmp_path),
    )

    def partial_apply(proposal: PatchProposal) -> None:
        del proposal
        target_file.write_text("value = 2\n", encoding="utf-8")
        raise PatchApplyError("simulated partial apply failure")

    monkeypatch.setattr(service.patch_applier, "validate", lambda proposal: None)
    monkeypatch.setattr(service.patch_applier, "apply", partial_apply)

    result = service.execute(
        dry_run=True,
        patch=build_patch(),
        summary="summary",
        fix_generator=StubFixGenerator(),
        selected_issue=build_issue(),
        context=build_context(),
        patch_factory=lambda **kwargs: build_patch(),
    )

    assert result.failure is not None
    assert result.failure.stage.value == "patch_apply"
    assert target_file.read_text(encoding="utf-8") == "value = 1\n"


def test_patch_execution_service_stops_before_patch_when_setup_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = PatchExecutionService(
        config=build_config(
            validation_setup_commands=["uv sync --locked"],
            validation_commands=["uv run pytest"],
        ),
        patch_applier=PatchApplier(tmp_path),
        validator=Validator(tmp_path),
        workspace_snapshot_service=WorkspaceSnapshotService(tmp_path),
    )
    setup_result = ValidationResult(
        passed=False,
        results=[
            ValidationCommandResult(
                command="uv sync --locked",
                exit_code=127,
                stdout="",
                stderr="uv: command not found",
                duration_ms=1,
            )
        ],
        summary="Validation could not run: uv sync --locked.",
    )
    monkeypatch.setattr(service.validator, "run", lambda commands: setup_result)
    monkeypatch.setattr(
        service.patch_applier,
        "apply",
        lambda proposal: (_ for _ in ()).throw(AssertionError("patch must not be applied")),
    )

    result = service.execute(
        dry_run=True,
        patch=build_patch(),
        summary="summary",
        fix_generator=StubFixGenerator(),
        selected_issue=build_issue(),
        context=build_context(),
        patch_factory=lambda **kwargs: build_patch(),
    )

    assert result.failure is not None
    assert result.failure.stage.value == "validation_setup"
    assert result.failure.failed_command == "uv sync --locked"


def test_patch_execution_service_runs_setup_once_before_validation_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = PatchExecutionService(
        config=build_config(
            validation_setup_commands=["uv sync --locked"],
            validation_commands=["uv run pytest"],
            max_retry_count=1,
        ),
        patch_applier=PatchApplier(tmp_path),
        validator=Validator(tmp_path),
        workspace_snapshot_service=WorkspaceSnapshotService(tmp_path),
    )
    commands_run: list[list[str]] = []
    results = iter(
        [
            ValidationResult(passed=True, results=[], summary="All validation commands passed."),
            ValidationResult(
                passed=False,
                results=[
                    ValidationCommandResult(
                        command="uv run pytest",
                        exit_code=1,
                        stdout="",
                        stderr="failure",
                        duration_ms=1,
                    )
                ],
                summary="Validation failed: uv run pytest (exit code 1).",
            ),
            ValidationResult(passed=True, results=[], summary="All validation commands passed."),
        ]
    )

    def run(commands: list[str]) -> ValidationResult:
        commands_run.append(commands)
        return next(results)

    monkeypatch.setattr(service.validator, "run", run)
    monkeypatch.setattr(
        service.validator,
        "repository_status",
        lambda: ValidationCommandResult(
            command="git status --porcelain",
            exit_code=0,
            stdout="",
            stderr="",
            duration_ms=1,
        ),
    )
    monkeypatch.setattr(service.patch_applier, "validate", lambda proposal: None)
    monkeypatch.setattr(service.patch_applier, "apply", lambda proposal: None)

    result = service.execute(
        dry_run=True,
        patch=build_patch(),
        summary="summary",
        fix_generator=StubFixGenerator(),
        selected_issue=build_issue(),
        context=build_context(),
        patch_factory=lambda **kwargs: build_patch(),
    )

    assert result.validation_passed is True
    assert commands_run == [
        ["uv sync --locked"],
        ["uv run pytest"],
        ["uv run pytest"],
    ]


def test_patch_execution_service_rejects_setup_that_changes_repository_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = PatchExecutionService(
        config=build_config(
            validation_setup_commands=["uv sync --locked"],
            validation_commands=["uv run pytest"],
        ),
        patch_applier=PatchApplier(tmp_path),
        validator=Validator(tmp_path),
        workspace_snapshot_service=WorkspaceSnapshotService(tmp_path),
    )
    monkeypatch.setattr(
        service.validator,
        "run",
        lambda commands: ValidationResult(
            passed=True,
            results=[],
            summary="All validation commands passed.",
        ),
    )
    monkeypatch.setattr(
        service.validator,
        "repository_status",
        lambda: ValidationCommandResult(
            command="git status --porcelain",
            exit_code=0,
            stdout=" M pyproject.toml\n",
            stderr="",
            duration_ms=1,
        ),
    )
    monkeypatch.setattr(
        service.patch_applier,
        "apply",
        lambda proposal: (_ for _ in ()).throw(AssertionError("patch must not be applied")),
    )

    result = service.execute(
        dry_run=True,
        patch=build_patch(),
        summary="summary",
        fix_generator=StubFixGenerator(),
        selected_issue=build_issue(),
        context=build_context(),
        patch_factory=lambda **kwargs: build_patch(),
    )

    assert result.failure is not None
    assert result.failure.stage.value == "validation_setup"
    assert result.failure.failed_command == "git status --porcelain"
