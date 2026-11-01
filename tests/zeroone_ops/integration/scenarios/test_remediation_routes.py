"""Characterize recorded publication and same-request revision using real Git."""

from datetime import UTC, datetime

import httpx
import pytest

from zeroone_ops.models.work_item import (
    ProjectedReviewFeedback,
    ProjectedReviewFinding,
    ProjectedReviewState,
    ReviewRevisionRequest,
)

from .harness import RUN_ID, compose_scenario
from .provider_api import ScenarioProviderAPI
from .repository import TARGET_PATH, create_repository, git
from .revision import RevisionModel, configure_request_lookup, persist_work_item


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("uncertain_create", [False, True])
def test_recorded_retry_publishes_existing_commit_without_execution(
    tmp_path, monkeypatch, platform, uncertain_create
):
    repository = create_repository(tmp_path)
    api = ScenarioProviderAPI(platform, allow_request_reuse=uncertain_create)
    fail_create = True

    def respond(request):
        if (
            fail_create
            and request.method == "POST"
            and request.url.path.endswith(("/pulls", "/merge_requests"))
        ):
            if uncertain_create:
                api.respond(request)
            return httpx.Response(503, json={"message": "Temporary publication outage"})
        return api.respond(request)

    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(respond)
    ) as http:
        harness = compose_scenario(repository, api, http, (None,), monkeypatch)
        harness.sync("promotion")
        original = harness.work_item()
        failed = harness.runner.run(record=harness.runs.start_run(RUN_ID), active_dry_run=False)
        blocked = harness.work_item()
        assert failed.status.value == "failed" and blocked.status == "blocked"
        retry = blocked.publication_retry
        assert retry is not None
        assert len(api.requests) == int(uncertain_create)
        assert blocked.claim is None
        assert (
            git(repository.remote, "rev-parse", f"refs/heads/{retry.branch_name}")
            == retry.commit_sha
        )
        api.branch_head_lookup = lambda branch: git(
            repository.remote, "rev-parse", f"refs/heads/{branch}"
        )
        configure_request_lookup(harness, http)
        blocked = blocked.model_copy(
            update={
                "batch": blocked.batch.model_copy(
                    update={
                        "observations": tuple(
                            observation.model_copy(update={"last_confirmed_presence": "absent"})
                            for observation in blocked.batch.observations
                        )
                    }
                )
            }
        )
        persist_work_item(harness, blocked.model_copy(update={"status": "approved"}))
        before = git(repository.root, "rev-parse", "HEAD")
        model_counts = (len(harness.model.analysis_contexts), len(harness.model.edit_contexts))
        validations = []
        original_validation = harness.engine.analysis_service.validator.run_all

        def validation(commands):
            validations.append(commands)
            return original_validation(commands)

        monkeypatch.setattr(harness.engine.analysis_service.validator, "run_all", validation)
        monkeypatch.setattr(
            harness.engine.branch_manager,
            "push_current_branch",
            lambda: pytest.fail("Recorded retry must not push"),
        )
        monkeypatch.setattr(
            harness.runner,
            "load_batch_policy",
            lambda: pytest.fail("Recorded retry must not load fresh policy"),
        )
        if not uncertain_create:
            repeat = harness.runner.run(
                record=harness.runs.start_run("retry-failed"), active_dry_run=False
            )
            assert repeat.status.value == "failed"
            assert harness.work_item().publication_retry == retry
            assert harness.work_item().claim is None
            persist_work_item(
                harness, harness.work_item().model_copy(update={"status": "approved"})
            )
        fail_create = False
        summary = harness.runner.run(
            record=harness.runs.start_run("retry-success"), active_dry_run=False
        )
        final = harness.work_item()
        assert summary.status.value == "change_request_created", summary.message
        action = "reused" if uncertain_create else "created"
        assert f"Change request {action}:" in summary.message
        assert final.status == "in_progress" and final.claim is None
        assert final.publication_retry is None and final.linked_change_request is not None
        assert final.batch.members == original.batch.members
        assert final.batch_attempt == retry.batch_attempt
        assert final.semantic_safety.assessment == retry.semantic_safety
        assert len(api.requests) == 1
        assert model_counts == (
            len(harness.model.analysis_contexts),
            len(harness.model.edit_contexts),
        )
        assert not validations
        assert git(repository.root, "rev-parse", "HEAD") == before == retry.commit_sha
        assert (
            git(
                repository.remote,
                "rev-list",
                "--count",
                f"{repository.original_sha}..{retry.commit_sha}",
            )
            == "1"
        )
        assert (
            git(repository.remote, "diff", "--name-only", repository.original_sha, retry.commit_sha)
            == TARGET_PATH
        )


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("succeeds", [True, False])
def test_revision_uses_verified_checkout_and_original_request(
    tmp_path, monkeypatch, platform, succeeds
):
    repository = create_repository(tmp_path)
    api = ScenarioProviderAPI(platform)
    with httpx.Client(
        base_url="https://provider.invalid", transport=httpx.MockTransport(api.respond)
    ) as http:
        harness = compose_scenario(repository, api, http, (None,), monkeypatch)
        harness.sync("promotion")
        first = harness.runner.run(record=harness.runs.start_run(RUN_ID), active_dry_run=False)
        assert first.status.value == "change_request_created"
        original = harness.work_item()
        branch = git(repository.root, "branch", "--show-current")
        sha = git(repository.root, "rev-parse", "HEAD")
        source = repository.source.read_text()
        api.branch_head_lookup = lambda branch: git(
            repository.remote, "rev-parse", f"refs/heads/{branch}"
        )
        configure_request_lookup(harness, http)
        feedback = ProjectedReviewFeedback(
            summary="Preserve value",
            finding_count=1,
            findings=[
                ProjectedReviewFinding(
                    title="Keep constant",
                    file_path=TARGET_PATH,
                    evidence="Keep the exported value",
                    explanation="Callers import value",
                    suggested_follow_up="Annotate without changing it",
                )
            ],
        )
        queued = original.model_copy(
            update={
                "status": "review_revision_queued",
                "projected_review": ProjectedReviewState(
                    classification="findings_present",
                    reviewed_sha=sha,
                    follow_up_required=True,
                    feedback=feedback,
                ),
                "review_revision_request": ReviewRevisionRequest(
                    actor="operator",
                    request_reference="note:1",
                    occurred_at=datetime.now(UTC),
                    reviewed_sha=sha,
                ),
            }
        )
        persist_work_item(harness, queued)
        model = RevisionModel(harness, repository, original, sha, succeeds)
        monkeypatch.setattr(harness.engine.analysis_service, "_build_llm_client", lambda: model)
        git(repository.root, "checkout", "main")
        writes_before = len(api.calls)

        summary = harness.runner.run(
            record=harness.runs.start_run("revision"), active_dry_run=False
        )

        final = harness.work_item()
        assert final.status == ("in_progress" if succeeds else "review_feedback_required"), (
            summary.message
        )
        assert final.claim is None and final.review_revision_request is None
        assert final.last_revision_command.request_reference == "note:1"
        assert final.linked_change_request == original.linked_change_request
        assert final.projected_review.feedback == feedback
        assert final.batch.members == original.batch.members
        assert final.batch_attempt.members == original.batch_attempt.members
        assert len(api.requests) == 1
        assert not any(
            path.endswith(("/pulls", "/merge_requests")) for _, path in api.calls[writes_before:]
        )
        assert model.analysis_count == 1 and model.edit_count == (1 if succeeds else 2)
        remote_sha = git(repository.remote, "rev-parse", f"refs/heads/{branch}")
        if succeeds:
            assert summary.status.value == "change_request_created"
            assert remote_sha != sha
            assert git(repository.remote, "rev-parse", f"{remote_sha}^") == sha
            assert git(repository.remote, "diff", "--name-only", sha, remote_sha) == TARGET_PATH
        else:
            assert summary.status.value == "failed"
            assert remote_sha == sha
            assert repository.source.read_text() == source
            assert git(repository.root, "rev-parse", "HEAD") == sha
            assert (
                final.execution_failure.diagnostic_excerpt
                and "NameError" in final.execution_failure.diagnostic_excerpt
            )
        assert git(repository.root, "diff", "--name-only") == ""
