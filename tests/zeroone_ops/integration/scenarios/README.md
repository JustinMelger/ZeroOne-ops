# Offline Workflow Scenarios

Run `just test-scenarios` from the repository root after installing development
dependencies with `uv sync --all-groups`. The recipe uses `uv run --no-sync` to
avoid network resolution or lockfile updates during an offline run.
Ordinary `uv run pytest` also collects these tests, so the existing
Quality workflow runs them on pull requests and `main` without another CI job.

## Remediation Scenarios

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

## Review Scenarios

Both providers run three additional cases: an introduced annotation defect is
retained, a pre-existing candidate is explicitly dropped, and two requests at
the same file path are reviewed sequentially without sharing request-specific
evidence. Real review clients, context selection, candidate/precision services,
artifact validation, rendering, publication, state persistence, and linked
work-item lookup/projection run without replacing their decisions.

The real LLM adapter renders prompts and selects schemas; a finite SDK-response
script checks actual request inputs and returns typed results. This does not
exercise SDK JSON parsing or establish model judgment. Scripted decisions are
intentional test inputs, not captured model responses. Source snapshots reuse
the frozen precision-investigation fixtures, with new local commits, request
markers, and a common file path. They are not historical MR executions.

The retained case seeds valid renderer-owned batch state. Both model stages
must receive the same verified member packet and rationale, and the final
comment, inline location, stored artifact, diagnostics, and projected issue
must agree. Isolation uses separate checkouts and shared provider/review state.
Repository scoping is checked at the HTTP boundary; the harness does not add
new repository fields to production prompts or production checkout checks.

A repeated-review scenario advances one request through three actual commits:
an undefined annotation, the same concern after line/wording changes, then its
fix alongside a new undefined annotation in another function. The real prior-note
loader and overlap service run with scripted SDK overlap responses. Tests verify
latest-prior SHA selection, unresolved versus resolved/new outcomes, inline-comment
reuse, independent published comments, bounded local history, and latest work-item
projection. A negative contract removes precision history and must fail before
another review is published. These checks verify continuity wiring, not whether
a real model correctly judges two findings to be equivalent.

Negative contracts remove source or batch evidence, corrupt forwarded candidate
evidence, substitute another checkout's context, and redirect publication. Each
must fail rather than let the SDK script manufacture a successful review.
Response snapshots are deep copies, independent of emitted responses and fixture
expectations. Negative tests also change final finding severity, evidence, impact,
and follow-up to verify that persisted meaning still matches precision output.

## Isolation And Live Evaluation

Only basic process environment is inherited; Git configuration/identity are local,
Git transport is file-only, tracing is disabled, `.env` loading is rejected, and
child pytest plugin/options inheritance is removed. Unexpected HTTP endpoints,
model requests, or parent-process socket connections fail. This is not an OS
network sandbox: child-process isolation relies on the fixed local validation
command and local-only Git transport. Dependency installation happens before
the tests, not inside the application fixture.

These scenarios test orchestration, not model quality, authorization, live API
compatibility, same-SHA reuse, projection-repair chains,
operator requeue, or lifecycle completion. Existing focused overlap/continuity tests
remain in place. The GitLab test app remains the separate, explicitly authorized
real-model/real-provider release-candidate acceptance environment. No live
evaluation is triggered by this suite.
