# AI Sonar Bot Roadmap

## Purpose

This roadmap translates the functional and technical design into an implementation sequence for v1.

It is intentionally short and execution-focused. The goal is to make the next steps obvious and keep scope controlled while the bot is being built.

Working rule:

- after each meaningful implementation round, pause for a short cleanup review
  before starting the next feature slice
- use that review to check workflow boundaries, growing files/services, test
  gaps, and any documentation drift created by the last round

## Current Status

Completed:

- [x] functional design
- [x] technical design
- [x] Python project scaffold with `uv`
- [x] local quality tooling with `ruff`, `mypy`, `pytest`, and `pytest-cov`
- [x] architecture boundary checks with `import-linter`
- [x] GitHub Actions quality workflow
- [x] local `just` commands
- [x] SonarQube client implementation
- [x] automatic `.env` loading
- [x] service-level refactor for issue intake and analysis orchestration
- [x] runner refactor into execution and run-state services
- [x] issue selection wired into the runner
- [x] code context analysis
- [x] LLM integration
- [x] patch application
- [x] git branch and commit automation
- [x] GitLab merge request creation
- [x] CI execution mode

Still open:

- [x] richer failure logging in state and logs

## Completed Milestones

### Sonar Remediation V1

Completed summary:

- end-to-end Sonar remediation from intake through GitLab merge request
  creation
- structured-edit and bot-rendered diff pipeline for the narrow single-file
  safe-fix path
- CI execution support, state persistence, duplicate protection, rollback, and
  operator runbook coverage
- enough testing and hardening to make the workflow stable and diagnosable

### PR Review Bot V1

Completed summary:

- GitLab merge request intake, dedup by MR IID and head SHA, and bounded diff
  context building
- structured review analysis with deterministic review note publishing
- shared CLI/state integration, rollout docs, and smoke-test guidance
- baseline hardening for no-findings, findings-present, and unchanged-SHA skip

## Next Selected Build: PR Review Bot V1

This is the next active implementation track after the SonarQube remediation
v1. It follows:

- [functional-design-pr-review.md](docs/functional-design-pr-review.md)
- [technical-design-pr-review.md](docs/technical-design-pr-review.md)

### Review Phase 1: Merge Request Intake

Goal:

- fetch open GitLab merge requests
- normalize merge request metadata
- support selecting one MR per run

Status:

- [x] add review-specific models for merge request metadata and changed files
- [x] add a GitLab review client for open merge request listing and detail retrieval
- [x] add `MergeRequestIntake` with typed no-work summaries

Done when:

- the bot can fetch open merge requests from GitLab
- merge request payloads are normalized consistently
- a dry-run can report real merge request counts

### Review Phase 2: Review Selection and Dedup

Goal:

- choose one reviewable merge request per run
- avoid duplicate reviews for the same MR revision

Status:

- [x] add `MergeRequestSelector`
- [x] store and compare dedup keys based on MR IID and head SHA
- [x] skip unchanged merge requests cleanly and move to the next eligible MR

Done when:

- the bot reviews at most one MR per run
- unchanged MR revisions are skipped without publishing duplicate notes
- run summaries explain why an MR was skipped

### Review Phase 3: Diff and Context Building

Goal:

- collect merge request diff data
- map changed files to the local repository
- build stable review context for the LLM

Status:

- [x] add `ReviewContextBuilder`
- [x] load changed files and surrounding source context
- [x] cap changed-file count and per-file context size for v1

Done when:

- the bot can build deterministic review context from one MR
- oversized or unsupported MRs are rejected cleanly
- changed-file context is stable enough for prompt construction

### Review Phase 4: Structured Review Analysis

Goal:

- request structured findings from the LLM
- distinguish no-findings from findings-present and insufficient-context cases

Status:

- [x] add review-specific finding/result models
- [x] add `ReviewAnalysisService`
- [x] validate LLM output shape before publishing

Done when:

- the LLM returns structured review results
- malformed or oversized review outputs are rejected
- the bot can classify review results deterministically

### Review Phase 5: Review Note Publishing

Goal:

- publish one deterministic merge request note
- keep output readable and non-spammy

Status:

- [x] add `ReviewPublisher`
- [x] render one deterministic summary note template
- [x] support both findings-present and no-findings note shapes

Done when:

- the bot can publish one MR note through GitLab
- findings are formatted consistently
- no-findings output is distinguishable from failure to review

### Review Phase 6: Review State and Runner Integration

Goal:

- persist review outcomes
- wire the review workflow into the shared CLI and state system

Status:

- [x] add review state records keyed by MR IID and head SHA
- [x] add a review runner path and CLI subcommand
- [x] keep the review workflow in the shared image with separate commands

Done when:

- review outcomes are persisted in state
- the CLI can run the review workflow explicitly
- the shared image can execute either Sonar remediation or PR review

### Review Phase 7: Hardening

Goal:

- make the review bot usable in real GitLab workflows
- keep reviews useful and low-noise

Status:

- [x] add tests for no-findings and findings-present review paths
- [x] add integration coverage for unchanged-SHA skip
- [x] document operator usage and rollout expectations
- [x] add a smoke-test recipe for one real merge request review run

Done when:

- the bot avoids duplicate notes for unchanged MR revisions
- the review note format is stable and readable
- another engineer can run and validate the review bot from docs alone

### Completed: Runner Cleanup

Goal:

- shrink `runner.py` back into a thin composition layer before adding more
  workflow complexity
- move workflow-specific orchestration into dedicated runner services with
  clearer ownership boundaries

Status:

- [x] extract the dashboard reconciliation workflow from `runner.py` into a
      dedicated runner service
- [x] extract the dashboard remediation workflow from `runner.py` into a
      dedicated runner service
- [x] extract the review workflow from `runner.py` into a dedicated runner
      service
- [x] remove the deprecated direct Sonar remediation path after extraction
- [x] keep `runner.py` as a thin delegation layer that builds shared
      dependencies and dispatches to workflow runners
- [x] add regression coverage proving the refactor preserves current CLI-facing
      summaries and failure behavior

Done when:

- `runner.py` is primarily a composition root instead of a multi-workflow
      orchestration file
- each workflow has a clearer dedicated home for its orchestration logic
- the next review-bot improvements can land without making workflow boundaries
      harder to maintain

### Following Phase: Review Bot Improvements

Goal:

- improve operator trust in the review bot before widening its role in the
      platform
- make review output more useful, evidence-backed, and lower-noise

Status:

- [x] teach the review workflow to use remediation-authored MR context when it
      is available, while degrading gracefully for normal human-authored merge
      requests
- [x] suppress speculative or weak findings more aggressively so the bot
      prefers no-findings over noisy low-confidence review output
- [x] strengthen finding formatting so each review comment ties the risk to
      concrete diff evidence or nearby source context
- [x] harden the review prompt against input poisoning by treating MR titles,
      descriptions, remediation context, diffs, and code snippets as untrusted
      data rather than instructions
- [x] delimit untrusted MR text, remediation metadata, diffs, and source
      context more explicitly in the review prompt so the model sees them as
      artifacts instead of executable guidance
- [x] validate structured review findings more aggressively after generation so
      evidence stays tied to reviewed files and weak unsupported findings are
      downgraded or rejected safely
- [ ] add advisory `review_confidence` and `review_confidence_reason` so the
      review bot exposes a clear operator trust signal without becoming a gate
- [x] make manual-review-only outcomes clearer so operators can distinguish
      insufficient context from low-value findings
- [ ] add repo-level controls for review noise such as path filtering,
      changed-file limits, and note verbosity
- [ ] capture human feedback and convert incorrect or noisy review comments
      into targeted regression tests

Done when:

- review notes feel conservative, evidence-backed, and useful in real merge
      request workflows
- remediation-authored merge requests get richer review quality without making
      review dependent on bot-authored changes
- new review noise or quality issues are routinely turned into regression tests

## Completed Build: Dashboard And Remediation

Completed summary:

- shared GitLab dashboard with deterministic parsing, rendering, retention, and
  operator-facing workflow guidance
- review-status mirroring and Sonar discovery mirroring without replacing MR
  notes or collapsing discovery into remediation
- dashboard-backed remediation from item intake through remediation-native
  execution, lifecycle updates, and CI-only rollout hardening
- scheduled reconciliation that closes the lifecycle loop for `mr_opened`
  items based on merge-request outcomes while preserving remediation metadata

## Ongoing Operations

These are continuous operating tasks, not blockers for later implementation
phases.

- continuously collect real production failure examples and turn them into
  regression tests
- continuously document recurring skip, reject, and failure patterns from live
  runs
- continuously review MR quality and false-positive/noise patterns for Sonar
  and review workflows
- security tooling is introduced gradually enough to keep CI signal usable

## Beyond V1

Post-v1 ideas and expansion tracks now live in
[future_plans.md](future_plans.md).

That includes:

- GitLab dashboard issue support
- symbol-safe rename handling
- complex single-file refactors
- GitHub support
- Renovate-style GitLab token handling
- broader platform expansion such as pipeline failure and review workflows
- in CI mode, derive the authenticated push remote from `GITLAB_TOKEN`,
  `CI_SERVER_HOST`, and `CI_PROJECT_PATH`
- keep CI config as a fallback, not the only place where push auth is wired

Rules:

- do not mix git transport concerns into the GitLab API client
- keep token handling centralized and explicit
- preserve compatibility with environments that already provide authenticated
  remotes

Done when:

- CI mode can push branches with `GITLAB_TOKEN` without requiring manual remote
  rewriting in `.gitlab-ci.yml`
- GitLab API calls and git push operations use one coherent credential model
- the GitLab CI example becomes simpler because push auth is configured by the
  bot runtime

## Working Rule

For v1, prefer shipping thin vertical slices over building all abstractions first.

Each phase should end with:

- working code,
- tests,
- passing quality checks,
- updated docs if behavior changes.
