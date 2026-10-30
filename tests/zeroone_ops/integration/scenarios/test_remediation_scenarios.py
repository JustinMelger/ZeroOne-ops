"""Exercise promotion through real validation and local Git publication offline."""

from pathlib import Path

import httpx
import pytest

from zeroone_ops.models.analysis import ValidationResult
from zeroone_ops.models.state import RunStatus

from .harness import RUN_ID, ScenarioHarness, compose_scenario
from .provider_api import Platform, ScenarioProviderAPI
from .repository import ORIGINAL_SOURCE, TARGET_PATH, ScenarioRepository, create_repository, git


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize(
    ("replacements", "expected_exits"),
    [
        pytest.param((None,), [0, 0], id="successful-batch"),
        pytest.param(
            ("value: MissingType = 1", "value: int = 1"),
            [0, 2, 0],
            id="successful-correction",
        ),
        pytest.param(
            ("value: MissingType = 1", "value: MissingType = 1"),
            [0, 2, 2],
            id="exhausted-correction",
        ),
    ],
)
def test_remediation_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: Platform,
    replacements: tuple[str | None, ...],
    expected_exits: list[int],
) -> None:
    repository = create_repository(tmp_path)
    api = ScenarioProviderAPI(platform)
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_scenario(repository, api, http, replacements, monkeypatch)

        promoted = harness.sync("scenario-promotion")
        assert promoted.created_count == promoted.promoted_count == 1
        assert promoted.selected_member_count == 2
        original = harness.work_item()
        assert original.status == "approved" and original.claim is None
        assert original.batch is not None and len(original.batch.members) == 2
        assert {member.finding_id for member in original.batch.members} == {
            finding.finding_id for finding in harness.findings
        }

        validator = harness.engine.analysis_service.validator
        run_validation = validator.run_all
        validation_results: list[ValidationResult] = []
        validation_sources: list[str] = []

        def observe_validation(commands: list[str]) -> ValidationResult:
            assert commands == [repository.validation_command]
            validation_sources.append(repository.source.read_text())
            result = run_validation(commands)
            validation_results.append(result)
            return result

        monkeypatch.setattr(validator, "run_all", observe_validation)
        summary = harness.runner.run(record=harness.runs.start_run(RUN_ID), active_dry_run=False)
        final = harness.work_item()
        assert final.work_item_id == original.work_item_id
        assert final.batch.members == original.batch.members
        assert final.claim is None
        assert final.batch_attempt is not None
        assert final.batch_attempt.run_id == RUN_ID
        assert set(final.batch_attempt.coverage.addressable_ids) == {
            member.finding_id for member in original.batch.members
        }
        assert len(harness.model.analysis_contexts) == 1
        assert len(harness.model.edit_contexts) == len(replacements)
        written_states = [harness.parse(payload) for payload in api.issue_writes]
        assert written_states[0] == original
        assert any(
            state.claim is not None
            and state.claim.run_id == RUN_ID
            and state.batch_attempt is not None
            for state in written_states
        )
        assert [result.results[0].exit_code for result in validation_results] == expected_exits
        assert validation_sources[0] == ORIGINAL_SOURCE
        assert all(source != ORIGINAL_SOURCE for source in validation_sources[1:])
        if len(expected_exits) == 3:
            assert "NameError" in validation_results[1].results[0].stdout
            assert "tests/test_service.py" in validation_results[1].results[0].stdout
            first_context, retry_context = harness.model.edit_contexts
            assert first_context.batch_attempt == retry_context.batch_attempt
            assert first_context.semantic_safety == retry_context.semantic_safety
        assert harness.runs.state_store.load().runs[-1].status == summary.status

        if expected_exits[-1] == 0:
            assert summary.status == RunStatus.CHANGE_REQUEST_CREATED, summary.message
            assert_successful_publication(harness, repository)
            again = harness.sync("scenario-repeat")
            assert again.created_count == again.promoted_count == again.backlog_only_count == 0
            assert len(api.issues) == len(api.requests) == 1
            assert harness.work_item().linked_change_request == final.linked_change_request
        else:
            assert summary.status == RunStatus.FAILED, summary.message
            assert_blocked_without_publication(harness, repository)


def assert_successful_publication(harness: ScenarioHarness, repository: ScenarioRepository) -> None:
    """Check actual provider evidence and the one-file commit stored in origin."""
    api = harness.api
    final = harness.work_item()
    assert final.status == "in_progress"
    assert final.semantic_safety.assessment is not None
    assert len(api.requests) == 1
    request = next(iter(api.requests.values()))
    description = str(request["body" if api.platform == "github" else "description"])
    assert "Validation passed" in description
    assert "Change Rationale" in description
    assert all(member.finding_id in description for member in final.batch.members)
    assert final.linked_change_request.number == request["number"]
    branch = str(request["head" if api.platform == "github" else "source_branch"])
    published_sha = git(repository.remote, "rev-parse", f"refs/heads/{branch}")
    assert published_sha == git(repository.root, "rev-parse", "HEAD")
    assert git(repository.remote, "rev-parse", "refs/heads/main") == repository.original_sha
    assert (
        git(repository.remote, "rev-list", "--count", f"{repository.original_sha}..{published_sha}")
        == "1"
    )
    assert (
        git(repository.remote, "diff", "--name-only", repository.original_sha, published_sha)
        == TARGET_PATH
    )
    assert (
        git(repository.remote, "show", f"{published_sha}:{TARGET_PATH}")
        == repository.source.read_text().strip()
    )
    assert "import os" not in repository.source.read_text()
    assert "import sys" not in repository.source.read_text()
    assert git(repository.root, "diff", "--name-only") == ""


def assert_blocked_without_publication(
    harness: ScenarioHarness, repository: ScenarioRepository
) -> None:
    """Check rollback, failed-attempt evidence, and absence of remote publication."""
    api = harness.api
    final = harness.work_item()
    assert final.status == "blocked"
    assert final.linked_change_request is None
    assert final.publication_retry is None
    assert not api.requests
    assert (
        git(repository.remote, "for-each-ref", "--format=%(refname)", "refs/heads")
        == "refs/heads/main"
    )
    assert git(repository.root, "rev-parse", "HEAD") == repository.original_sha
    assert repository.source.read_text() == ORIGINAL_SOURCE
    assert git(repository.root, "diff", "--name-only") == ""
    failure = final.execution_failure
    assert failure is not None
    assert failure.failed_command == repository.validation_command
    assert failure.retry_count == 1
    assert failure.exit_code == 2 and failure.baseline_exit_code == 0
    assert failure.validation_phase == "post_edit"
    assert "NameError" in failure.diagnostic_excerpt
    assert "One correction attempt was used" in failure.summary
    field = "body" if api.platform == "github" else "description"
    body = str(next(iter(api.issues.values()))[field])
    assert "NameError" in body.split("## Machine State")[0]
    assert not any(path.endswith(("/pulls", "/merge_requests")) for _, path in api.calls)
