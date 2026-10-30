# Offline Workflow Scenarios

Run `just test-scenarios` from the repository root after installing development
dependencies with `uv sync --all-groups`. The recipe uses `uv run --no-sync` to
avoid network resolution or lockfile updates during an offline run.
Ordinary `uv run pytest` also collects these tests, so the existing
Quality workflow runs them on pull requests and `main` without another CI job.

Each scenario runs against GitHub and GitLab:

- Successful batch promotion, intake, validation, and publication.
- Passing baseline, a generated annotation causing pytest collection failure,
  one correction, and successful revalidation/publication.
- Exhausted correction, restored source, blocked work, and no publication.

The scenarios start with normalized findings, not scanner execution. Real public
finding-sync services, provider clients, parsers, renderers, intake, claims,
execution, and publication services run against in-memory HTTP responses and a
finite scripted model. Tests use a disposable application, real pytest
subprocesses, and real commits/pushes to a local bare Git remote. They inspect
serialized issue state and the pushed commit rather than accepting mocked
workflow outcomes. Validation observation wraps the real validator without
changing its results. Repeated sync verifies active ownership suppresses
duplicate creation.

Harness contract tests deliberately corrupt source/member evidence at analysis,
initial edit, and correction boundaries, and send invalid publication targets or
provider destinations. These must fail rather than produce scripted success.
The fake transport checks the expected provider, repository/project scope, and
target branch; the scripted model checks delivered source and batch evidence.

Only basic process environment is inherited; Git configuration/identity are local,
Git transport is file-only, tracing is disabled, `.env` loading is rejected, and
child pytest plugin/options inheritance is removed. Unexpected HTTP endpoints,
model requests, or parent-process socket connections fail. This is not an OS
network sandbox: child-process isolation relies on the fixed local validation
command and local-only Git transport. Dependency installation happens before
the tests, not inside the application fixture.

These scenarios test orchestration, not model quality, authorization, live API
compatibility, review/requeue, or lifecycle completion. Existing focused tests
remain in place. The GitLab test app remains the separate, explicitly authorized
real-model/real-provider release-candidate acceptance environment. No live
evaluation is triggered by this suite.
