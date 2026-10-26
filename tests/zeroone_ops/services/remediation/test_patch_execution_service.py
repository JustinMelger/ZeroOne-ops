import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

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


def validation_result(command: str, output: str, exit_code: int = 1) -> ValidationResult:
    return ValidationResult(
        passed=exit_code == 0,
        results=[
            ValidationCommandResult(
                command=command,
                exit_code=exit_code,
                stdout=output,
                stderr="",
                duration_ms=1,
            )
        ],
        summary="validation",
    )


@pytest.mark.parametrize("tool", ["mypy", "ruff"])
def test_import_removal_preserves_real_tool_diagnostics(tmp_path, monkeypatch, tool) -> None:
    source = tmp_path / "src/service.py"
    source.parent.mkdir()
    source.write_text("import os\nimport sys\n\ndef demo():\n    return 1\n", encoding="utf-8")
    arguments = (
        "--strict --no-incremental --no-error-summary --no-pretty --no-color-output"
        if tool == "mypy"
        else "check --isolated --select F401"
    )
    command = f"{sys.executable} -m {tool} {arguments} src/service.py"
    service = PatchExecutionService(
        config=build_config(validation_commands=[command], validation_feedback_enabled=True),
        patch_applier=PatchApplier(tmp_path),
        validator=Validator(tmp_path),
        workspace_snapshot_service=WorkspaceSnapshotService(tmp_path),
    )
    monkeypatch.setattr(service.patch_applier, "validate", lambda patch: None)
    monkeypatch.setattr(
        service.patch_applier,
        "apply",
        lambda patch: source.write_text(
            source.read_text(encoding="utf-8").replace("import os\n", ""),
            encoding="utf-8",
        ),
    )
    regenerate = Mock()
    outcome = service.execute(
        dry_run=True,
        patch=build_patch(),
        summary="summary",
        fix_generator=StubFixGenerator(),
        selected_issue=build_issue(),
        context=build_context(),
        patch_factory=regenerate,
    )
    assert outcome.validation_comparison is not None, outcome.summary
    assert outcome.validation_comparison.outcome == "baseline_preserved", outcome.summary
    assert outcome.patch_applied
    assert not outcome.validation_passed
    regenerate.assert_not_called()


@pytest.mark.parametrize("exit_code", [2, 124, 126, 127, -15])
def test_baseline_execution_failure_blocks_before_patch_or_regeneration(
    tmp_path: Path,
    monkeypatch,
    exit_code: int,
    caplog,
) -> None:
    command = "uv run mypy src"
    service = PatchExecutionService(
        config=build_config(
            validation_commands=[command], validation_feedback_enabled=True, max_retry_count=1
        ),
        patch_applier=PatchApplier(tmp_path),
        validator=Validator(tmp_path),
        workspace_snapshot_service=WorkspaceSnapshotService(tmp_path),
    )
    apply = Mock()
    regenerate = Mock()
    run_all = Mock(
        return_value=validation_result(command, "private diagnostic contents", exit_code)
    )
    monkeypatch.setattr(service.patch_applier, "apply", apply)
    monkeypatch.setattr(service.validator, "run_all", run_all)
    with caplog.at_level("INFO"):
        outcome = service.execute(
            dry_run=True,
            patch=build_patch(),
            summary="summary",
            fix_generator=StubFixGenerator(),
            selected_issue=build_issue(),
            context=build_context(),
            patch_factory=regenerate,
        )
    assert not outcome.patch_applied
    assert outcome.failure is not None
    assert outcome.failure.validation_outcome == "unscoped_regression"
    apply.assert_not_called()
    regenerate.assert_not_called()
    run_all.assert_called_once_with([command])
    assert "private diagnostic contents" not in caplog.text
    assert "enabled=True" in caplog.text


def test_retries_compare_actual_source_to_original_baseline_and_restore_between_attempts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "src/service.py"
    source.parent.mkdir()
    original = "import os\ndef demo():\n    return 1\n"
    source.write_text(original, encoding="utf-8")
    command = "uv run mypy src"
    service = PatchExecutionService(
        config=build_config(
            validation_commands=[command], validation_feedback_enabled=True, max_retry_count=1
        ),
        patch_applier=PatchApplier(tmp_path),
        validator=Validator(tmp_path),
        workspace_snapshot_service=WorkspaceSnapshotService(tmp_path),
    )
    contents = iter(["def demo():\n    return 1\n", "\ndef demo():\n    return 1\n"])
    monkeypatch.setattr(service.patch_applier, "validate", lambda patch: None)
    monkeypatch.setattr(
        service.patch_applier,
        "apply",
        lambda patch: source.write_text(next(contents), encoding="utf-8"),
    )
    run_all = Mock(
        side_effect=[
            validation_result(
                command, "src/service.py:2: error: Missing annotation  [no-untyped-def]"
            ),
            validation_result(
                command,
                "src/service.py:1: error: Missing annotation  [no-untyped-def]\n"
                "src/service.py:2: error: Invalid attribute  [attr-defined]",
            ),
            validation_result(
                command, "src/service.py:2: error: Missing annotation  [no-untyped-def]"
            ),
        ]
    )
    monkeypatch.setattr(service.validator, "run_all", run_all)

    def regenerate(**kwargs):
        assert source.read_text(encoding="utf-8") == original
        feedback = kwargs["context"].validation_feedback
        assert feedback is not None
        assert len(feedback.failures) == 1
        assert "attr-defined" in feedback.failures[0].excerpt
        assert "Missing annotation" not in feedback.failures[0].excerpt
        return build_patch()

    outcome = service.execute(
        dry_run=True,
        patch=build_patch(),
        summary="summary",
        fix_generator=StubFixGenerator(),
        selected_issue=build_issue(),
        context=build_context(),
        patch_factory=regenerate,
    )
    assert outcome.validation_comparison is not None
    assert outcome.validation_comparison.outcome == "baseline_preserved"
    assert not outcome.validation_passed
    assert outcome.patch_applied
    assert run_all.call_count == 3
    assert source.read_text(encoding="utf-8") == "\ndef demo():\n    return 1\n"


def test_post_edit_execution_failure_restores_source_without_regeneration(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "src/service.py"
    source.parent.mkdir()
    source.write_text("original\n", encoding="utf-8")
    command = "uv run mypy src"
    service = PatchExecutionService(
        config=build_config(
            validation_commands=[command], validation_feedback_enabled=True, max_retry_count=1
        ),
        patch_applier=PatchApplier(tmp_path),
        validator=Validator(tmp_path),
        workspace_snapshot_service=WorkspaceSnapshotService(tmp_path),
    )
    monkeypatch.setattr(service.patch_applier, "validate", lambda patch: None)
    monkeypatch.setattr(
        service.patch_applier,
        "apply",
        lambda patch: source.write_text("changed\n", encoding="utf-8"),
    )
    monkeypatch.setattr(
        service.validator,
        "run_all",
        Mock(
            side_effect=[
                validation_result(command, "", 0),
                validation_result(command, "tool unavailable", 127),
            ]
        ),
    )
    regenerate = Mock()
    outcome = service.execute(
        dry_run=True,
        patch=build_patch(),
        summary="summary",
        fix_generator=StubFixGenerator(),
        selected_issue=build_issue(),
        context=build_context(),
        patch_factory=regenerate,
    )
    assert not outcome.patch_applied
    assert "validation environment" in outcome.summary
    assert source.read_text(encoding="utf-8") == "original\n"
    regenerate.assert_not_called()


class StubFixGenerator(FixGenerator):
    def __init__(self) -> None:
        pass


def build_config(
    *,
    validation_setup_commands: list[str] | None = None,
    validation_commands: list[str] | None = None,
    max_retry_count: int = 0,
    validation_feedback_enabled: bool = False,
) -> AppConfig:
    return AppConfig(
        base_branch="main",
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            target_branch="main",
            bootstrap_severities=["LOW"],
            validation_setup_commands=validation_setup_commands or [],
            validation_commands=validation_commands or [],
            max_retry_count=max_retry_count,
            validation_feedback_enabled=validation_feedback_enabled,
            analysis=AnalysisConfig(),
        ),
        gitlab=GitLabConfig(),
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
    assert result.failure.message.endswith("Inspect the workspace before retrying.")


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


def test_validation_setup_allows_configured_untracked_runtime_outputs(
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
            command="git status --porcelain=v1 -z --untracked-files=all",
            exit_code=0,
            stdout="?? .zeroone-ops-state.json\0?? artifacts/openai-solution.json\0",
            stderr="",
            duration_ms=1,
        ),
    )

    assert service._bootstrap_validation_environment() is None


def test_validation_setup_rejects_unconfigured_untracked_output(
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
            command="git status --porcelain=v1 -z --untracked-files=all",
            exit_code=0,
            stdout="?? artifacts/semgrep.sarif\0",
            stderr="",
            duration_ms=1,
        ),
    )

    failure = service._bootstrap_validation_environment()

    assert failure is not None
    assert failure.stage.value == "validation_setup"


def test_patch_execution_service_retries_once_with_actionable_validation_feedback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    service = PatchExecutionService(
        config=build_config(
            validation_commands=["ruff check ."],
            max_retry_count=1,
            validation_feedback_enabled=True,
        ),
        patch_applier=PatchApplier(tmp_path),
        validator=Validator(tmp_path),
        workspace_snapshot_service=WorkspaceSnapshotService(tmp_path),
    )
    results = iter(
        [
            ValidationResult(
                passed=True,
                results=[
                    ValidationCommandResult(
                        command="ruff check .",
                        exit_code=0,
                        stdout="",
                        stderr="",
                        duration_ms=1,
                    )
                ],
                summary="All validation commands passed.",
            ),
            ValidationResult(
                passed=False,
                results=[
                    ValidationCommandResult(
                        command="ruff check .",
                        exit_code=1,
                        stdout="src/service.py:1:1: E999 generated regression",
                        stderr="",
                        duration_ms=1,
                    )
                ],
                summary="Validation failed.",
            ),
            ValidationResult(
                passed=True,
                results=[
                    ValidationCommandResult(
                        command="ruff check .",
                        exit_code=0,
                        stdout="",
                        stderr="",
                        duration_ms=1,
                    )
                ],
                summary="All validation commands passed.",
            ),
        ]
    )
    feedback_contexts: list[IssueContext] = []
    monkeypatch.setattr(service.patch_applier, "validate", lambda proposal: None)
    monkeypatch.setattr(service.patch_applier, "apply", lambda proposal: None)
    monkeypatch.setattr(service.validator, "run_all", lambda commands: next(results))

    def patch_factory(**kwargs) -> PatchProposal:
        feedback_contexts.append(kwargs["context"])
        return build_patch()

    result = service.execute(
        dry_run=True,
        patch=build_patch(),
        summary="summary",
        fix_generator=StubFixGenerator(),
        selected_issue=build_issue(),
        context=build_context(),
        patch_factory=patch_factory,
    )

    assert result.validation_comparison is not None
    assert result.validation_comparison.outcome == "passed"
    assert result.patch_applied is True
    assert len(feedback_contexts) == 1
    assert feedback_contexts[0].validation_feedback is not None
    assert "src/service.py" in feedback_contexts[0].validation_feedback.failures[0].excerpt


def test_patch_execution_service_accepts_preserved_baseline_without_clean_claim(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    service = PatchExecutionService(
        config=build_config(
            validation_commands=["uv run mypy src"],
            validation_feedback_enabled=True,
        ),
        patch_applier=PatchApplier(tmp_path),
        validator=Validator(tmp_path),
        workspace_snapshot_service=WorkspaceSnapshotService(tmp_path),
    )
    known_failure = ValidationResult(
        passed=False,
        results=[
            ValidationCommandResult(
                command="uv run mypy src",
                exit_code=1,
                stdout="tests/unrelated.py:1: error: Missing annotation  [no-untyped-def]",
                stderr="",
                duration_ms=1,
            )
        ],
        summary="Validation failed.",
    )
    monkeypatch.setattr(service.patch_applier, "validate", lambda proposal: None)
    monkeypatch.setattr(service.patch_applier, "apply", lambda proposal: None)
    monkeypatch.setattr(service.validator, "run_all", lambda commands: known_failure)

    result = service.execute(
        dry_run=True,
        patch=build_patch(),
        summary="summary",
        fix_generator=StubFixGenerator(),
        selected_issue=build_issue(),
        context=build_context(),
        patch_factory=lambda **kwargs: build_patch(),
    )

    assert result.patch_applied is True
    assert result.validation_passed is False
    assert result.validation_comparison is not None
    assert result.validation_comparison.outcome == "baseline_preserved"


def test_patch_execution_service_reports_when_feedback_retry_is_not_permitted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    service = PatchExecutionService(
        config=build_config(
            validation_commands=["ruff check ."],
            max_retry_count=0,
            validation_feedback_enabled=True,
        ),
        patch_applier=PatchApplier(tmp_path),
        validator=Validator(tmp_path),
        workspace_snapshot_service=WorkspaceSnapshotService(tmp_path),
    )
    results = iter(
        [
            ValidationResult(
                passed=True,
                results=[
                    ValidationCommandResult(
                        command="ruff check .",
                        exit_code=0,
                        stdout="",
                        stderr="",
                        duration_ms=1,
                    )
                ],
                summary="Validation passed.",
            ),
            ValidationResult(
                passed=False,
                results=[
                    ValidationCommandResult(
                        command="ruff check .",
                        exit_code=1,
                        stdout="src/service.py:1:1: E999 generated regression",
                        stderr="",
                        duration_ms=1,
                    )
                ],
                summary="Validation failed.",
            ),
        ]
    )
    monkeypatch.setattr(service.patch_applier, "validate", lambda proposal: None)
    monkeypatch.setattr(service.patch_applier, "apply", lambda proposal: None)
    monkeypatch.setattr(service.validator, "run_all", lambda commands: next(results))

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
    assert result.failure.validation_outcome == "actionable_regression"
    assert "No correction attempt was permitted" in result.failure.message


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
