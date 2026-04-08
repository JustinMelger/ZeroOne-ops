# AI Sonar Bot Roadmap

## Purpose

This roadmap translates the functional and technical design into an implementation sequence for v1.

It is intentionally short and execution-focused. The goal is to make the next steps obvious and keep scope controlled while the bot is being built.

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

## V1 Delivery Phases

### Phase 1: SonarQube Intake

Goal:

- fetch open SonarQube issues for the configured project
- normalize issues into internal models
- verify local file mapping

Status:

- [x] fetch open SonarQube issues for the configured project
- [x] normalize issues into internal models
- [x] verify local file mapping

Done when:

- the bot can retrieve open issues from SonarQube
- issue payloads are normalized consistently
- dry-run can report real issue counts

### Phase 2: Issue Selection

Goal:

- filter unsupported issues
- skip issues already handled
- select one actionable issue per run
- persist selection state

Status:

- [x] filter unsupported issues
- [x] skip issues already handled
- [x] select one actionable issue per run
- [x] persist selection state

Done when:

- `IssueIntakeService` selects one eligible issue
- the selected issue is stored in state
- dry-run shows the selected issue key, file, rule, and severity

### Phase 3: Local Code Analysis

Goal:

- build source context around the issue location
- identify relevant file content for analysis
- prepare structured input for the LLM

Done when:

- [x] the context builder returns focused code context
- [x] missing files or missing lines are handled cleanly
- [x] the analysis input is stable enough for prompt construction
- [x] analysis orchestration is isolated in a dedicated service

### Phase 4: LLM Analysis and Patch Proposal

Goal:

- classify issues as fixable or manual
- generate a proposed patch
- generate commit and merge request metadata

Done when:

- [x] the LLM returns structured analysis data
- [x] the LLM returns structured patch data
- [x] invalid or unsafe responses are rejected
- [x] patch proposals are constrained to allowed files

### Phase 5: Patch Application and Validation

Goal:

- apply generated patches locally
- run repository validation commands
- support one retry after validation failure

Done when:

- [x] a generated patch can be applied safely
- [x] validation output is captured and summarized
- [x] failed validation can trigger one controlled retry

### Phase 6: Git Automation

Goal:

- verify repository preconditions
- create a work branch
- commit validated changes
- push the branch

Done when:

- [x] the bot creates a predictable branch name
- [x] unsafe repository states are rejected
- [x] commit and push work from the configured repository root

### Phase 7: GitLab Merge Request Creation

Goal:

- create a merge request in GitLab
- include labels and issue metadata
- avoid duplicate merge requests

Done when:

- [x] a validated branch can produce a GitLab merge request
- [x] the merge request contains SonarQube context
- [x] the local state records the merge request URL
- [x] duplicate open merge requests are reused instead of recreated

### Phase 8: Human Approval Gate

Goal:

- support non-interactive CI execution
- use GitLab merge request review as the approval gate in pipelines
- keep optional local interactive approval for developer-triggered runs

Done when:

- [x] CI mode bypasses terminal prompts and creates merge requests automatically
- [x] local mode can still request interactive approval when enabled
- [x] approval behavior is reflected in config and run state

### Phase 9: Hardening

Goal:

- improve test coverage
- add coverage thresholds
- improve logging and failure classification
- tighten duplicate-processing safeguards

Done when:

- [x] the main execution path is covered by tests
- [x] CI enforces an agreed minimum coverage threshold
- [x] failures are diagnosable from logs and state

### Phase 10: Bot-Rendered Diffs

Goal:

- replace raw LLM-authored unified diffs with bot-rendered diffs for narrow,
  low-risk fixes
- reduce patch-format failures and simplify the patch pipeline

Status:

- [x] add structured edit proposal models
- [x] add an edit renderer service for exact single-file replacements
- [x] generate unified diffs in the bot from old and new file content
- [x] update the OpenAI client to return structured edits for the narrow path
- [x] use structured edit mode first for low-risk single-file fixes
- [x] remove raw LLM-authored diff generation from the runtime path
- [x] reject ambiguous edits instead of guessing
- [x] add direct unit tests for the edit renderer
- [x] add integration coverage for structured edit -> diff -> apply -> validate
- [x] update technical docs after the new path is stable

### Phase 11: V1 Hardening

Goal:

- make repeated CI usage safer and more predictable
- tighten the allowed issue scope for low-risk automation
- improve operator visibility and supportability

Status:

- [x] add a duplicate-issue guard that skips work when the SonarQube issue key already has an open merge request or active branch, then selects the next eligible issue instead of updating the existing branch by default
- [x] persist structured edit artifacts alongside analysis and rendered patch output for better debugging
- [x] disable solution artifact file writing by default in CI mode so merge requests, logs, and state remain the primary traceability surfaces
- [x] verify rollback leaves the repository in a predictable state on approval rejection, patch-apply failure, and commit failure
- [x] tighten issue eligibility so v1 stays limited to low-risk single-file issues that fit the structured-edit model, including excluding rename-style SonarQube issues until symbol reference safety checks exist and rejecting multi-file structured edits as out of scope
- [x] improve logs and summaries so skip, reject, and ambiguity decisions are explicit
- [x] enforce a deterministic merge request description template with stable traceability fields such as issue key, rule, severity, file, issue message, validation summary, and bot-rendered diff note
- [x] split oversized orchestration services so analysis, patch execution, artifact output, and publish concerns stay testable and maintainable
- [x] add an operator runbook covering CI variables, token scopes, expected workflow behavior, and recovery steps
- [x] add a documented end-to-end smoke test recipe for validating the bot against a real target repository

Done when:

- repeated scheduled or manual CI runs do not create duplicate work for the same open issue
- when an issue already has an open bot merge request, the bot skips it and moves to the next eligible issue or exits cleanly if none remain
- operators can understand why an issue was skipped, rejected, or turned into a merge request without reading code
- the supported v1 issue scope is explicit in both config and docs
- another engineer can configure and operate the bot from the runbook alone

## Recommended Implementation Order

- [x] Wire issue selection into the runner.
- [x] Improve the context builder around issue file and line.
- [x] Extract issue intake and analysis orchestration into dedicated services.
- [x] Implement git precondition checks and branch creation.
- [x] Implement the GitLab client for merge request creation.
- [x] Implement LLM analysis and patch generation.
- [x] Implement patch apply and validation retry flow.
- [x] Add optional local approval flow.
- [x] Harden duplicate-MR messaging and reuse behavior.
- [x] Harden logging and failure handling.

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

## Next Phase: Dashboard And Operational Hardening

This is the next active phase after the SonarQube remediation v1 and PR review
bot v1 are both live.

The goal is to finish the dashboard foundation and stabilize the two existing
workflows in real CI usage before starting any new bot track.

It follows:

- [functional-design-dashboard.md](/Users/justinmelger/Desktop/github/ai-sonar-bot/docs/functional-design-dashboard.md)
- [technical-design-dashboard.md](/Users/justinmelger/Desktop/github/ai-sonar-bot/docs/technical-design-dashboard.md)

### Dashboard Phase 1: Dashboard Foundation

Goal:

- implement the GitLab dashboard issue as the shared visibility and control
  plane
- support deterministic rendering and parsing of structured dashboard items

Status:

- [x] add dashboard models
- [x] add a GitLab dashboard client for issue lookup, creation, and updates
- [x] add deterministic dashboard parser and renderer services
- [x] add a dashboard service that loads, merges, and publishes structured
      dashboard content

Done when:

- one dashboard issue can be created or reused deterministically
- structured dashboard sections render and parse without ambiguity
- the dashboard can be updated without duplicate item blocks

### Dashboard Phase 2: Review Status Mirroring

Goal:

- mirror PR review workflow outcomes to the dashboard without replacing MR notes

Status:

- [x] add review-status dashboard item models
- [x] add a review dashboard updater service
- [x] write reviewed SHA, review status, and MR links to the dashboard after a
      completed review run

Done when:

- merge request reviews still publish their primary output on the MR
- the dashboard shows review status for the reviewed MR revision
- repeated review runs do not create duplicate dashboard status items for the
  same MR IID and head SHA

### Dashboard Phase 3: Sonar Discovery Mirroring

Goal:

- mirror supported SonarQube discovery results to the dashboard as structured
  work items

Status:

- [x] add Sonar-to-dashboard normalization
- [x] write eligible Sonar items into the dashboard backlog without triggering
      remediation from the same workflow
- [x] preserve stable IDs and statuses for repeated Sonar discovery runs
- [x] reconcile existing Sonar dashboard items when issues disappear from
      SonarQube so stale active entries are marked done or moved out of active
      sections

Done when:

- supported Sonar items appear in the dashboard in a strict structured format
- repeated discovery runs update existing dashboard items instead of duplicating
  them
- stale Sonar dashboard items no longer remain active when they disappear from
  current SonarQube results
- discovery remains separate from remediation

### Dashboard Phase 4: Live Monitoring And Regression Capture

Goal:

- finish the dashboard-specific operational hardening needed for live use

Status:

- [x] improve review logs so MR selection, dedup skips, context size,
      classification, note publication, and dashboard mirroring are explicit in
      run output
- [x] tighten the review note templates so `no_findings` and findings summaries
      stay concise, readable, and low-noise in real merge requests
- [x] add a bounded dashboard retention rule so the main issue keeps only a
      maximum active/recent item window instead of growing without limit

Done when:

- review runs are diagnosable from logs without needing to inspect code paths
- review notes feel useful and lightweight instead of repetitive or noisy
- the main dashboard remains readable and operationally useful over time

### Dashboard Phase 5: Workflow Reliability And Test Hardening

Goal:

- improve live workflow reliability and test confidence around the current
  dashboard foundation

Status:

- [x] tighten GitLab CI examples and smoke-test guidance around the two current
      workflows
- [x] add integration coverage for the most important CI-facing workflow paths
- [x] add dashboard parser and renderer regression coverage
- [x] extract workflow prompts into separate prompt files so Sonar and review
      prompt policy can be reviewed and evolved without growing provider code

Done when:

- CI examples reflect the real supported workflow commands and image behavior
- the most important live workflow paths are covered by integration tests
- dashboard parsing/rendering is protected by regression coverage
- prompt instructions are easier to review and maintain across multiple
  workflows

### Post-Remedy Phase 6: CI/CD And Security Hardening

## Next Selected Build: Dashboard Remediation Bot V1

This is the next active implementation track after the dashboard foundation
work. It follows:

- [functional-design-dashboard-remediation.md](docs/functional-design-dashboard-remediation.md)
- [technical-design-dashboard-remediation.md](docs/technical-design-dashboard-remediation.md)

### Remediation Phase 1: Dashboard Item Intake

Goal:

- load the dashboard issue through the existing dashboard service
- select one remediation-ready item safely
- return clear no-work and skip outcomes

Status:

- [x] add provider-neutral remediation work-item models
- [x] add a dashboard item intake service that loads and selects one candidate
- [x] add a dashboard item selector that only considers supported `open` items
- [x] use stable dashboard item IDs as the primary dedup key and skip items
      already tracked as active in local state or represented by active merge
      requests
- [x] define and implement one explicit stale `in_progress` recovery rule for
      interrupted earlier runs
- [x] return stable skip reasons for unsupported status, unsupported type, and
      no-eligible-item outcomes

Done when:

- one dashboard-backed remediation candidate can be selected deterministically
- the workflow exits cleanly when no supported `open` item is available
- active local state and active merge requests prevent duplicate remediation of
      the same dashboard item
- stale `in_progress` items are handled by one explicit documented recovery rule
- selection logic is isolated from code-fixing logic

### Remediation Phase 2: Work Item Normalization And Context

Goal:

- normalize dashboard items into a provider-neutral remediation shape
- reuse the current safe single-file context-building model
- reject items that exceed current remediation scope

Status:

- [x] add a dashboard item normalizer that validates the remediation-ready item contract
- [x] add a remediation context builder that maps normalized work items onto the
      existing repository context flow
- [x] reject structurally incomplete or out-of-scope items before execution
- [x] keep the first supported type limited to the current Sonar-compatible
      single-file code-smell path

Done when:

- the remediation execution path no longer depends on raw dashboard field names
- supported items can produce the same bounded repository context used by the
      current Sonar remediation path
- unsupported items are skipped or rejected before patch execution starts

### Remediation Phase 3: Dashboard Lifecycle Updates

Goal:

- keep the dashboard in sync with remediation progress
- record stable item lifecycle transitions and traceability metadata
- keep first-version state ownership limited to transitions the remediation run
      can observe directly

Status:

- [x] add a dashboard remediation updater service for lifecycle transitions
- [x] keep lifecycle updates owned by that dedicated updater service instead of
      spreading dashboard state writes across runner, execution, or publish code
- [x] mark selected items `in_progress` before remediation execution
- [x] mark successful items `mr_opened` with branch name, merge request URL,
      and commit SHA
- [x] mark failed or rejected items with clear status and error context
- [x] support the `done` lifecycle state for items that no longer need
      remediation
- [x] stamp every lifecycle transition with `last_run_id` and
      `status_updated_at`
- [x] preserve existing non-lifecycle metadata when status transitions are
      written back to the dashboard item
- [x] keep dashboard item ID, run ID, branch name, commit SHA, and merge
      request URL visible across lifecycle updates and run summaries
- [x] keep lifecycle writes idempotent for retries or reruns of the same run ID
      where practical

Done when:

- item lifecycle transitions are owned by one dedicated service
- the dashboard shows `in_progress`, `mr_opened`, `failed`, `rejected`, and
      `done` states accurately for the remediation path
- lifecycle updates preserve existing remediation/discovery metadata instead of
      accidentally dropping fields during status changes
- operators can follow one dashboard item from selection to merge request or
      failure without reading logs first
- operators can correlate dashboard item, run, branch, commit, and merge
      request data across logs, summaries, and dashboard state
- the first remediation workflow owns only active-run transitions and does not
      try to reconcile later merged or closed merge requests yet

### Remediation Phase 4: Runner And CLI Wiring

Goal:

- expose dashboard-backed remediation as an explicit workflow
- keep the current Sonar remediation path available during migration

Status:

- [x] add a dedicated dashboard remediation CLI command
- [x] add a dashboard remediation runner path that wires intake, lifecycle
      updates, analysis, patch execution, and publish flow
- [x] keep the existing direct Sonar remediation command intact during migration
- [x] return clear run summaries for no-work, failed, rejected, and MR-opened
      outcomes
- [x] keep live dashboard remediation CI-only and local use limited to
      `--dry-run` in the first implementation

Done when:

- operators can run dashboard-backed remediation without hidden flags or local
      code changes
- the new runner path reuses the proven single-file remediation engine instead
      of duplicating it
- the old direct Sonar remediation path is clearly treated as deprecated
      fallback behavior rather than a long-term parallel workflow

### Remediation Phase 5: Migration Hardening And Rollout

Goal:

- prove that dashboard-backed remediation is safe enough to become the primary
      remediation workflow before live rollout
- document and test the deprecation path for the old direct Sonar remediation
      runner

Status:

- [x] add focused integration coverage for the dashboard remediation execution
      path
- [x] add rollback and lifecycle regression coverage for failed dashboard runs
- [x] add integration or smoke coverage for the documented stale `in_progress`
      recovery rule
- [x] document a smoke-test recipe for one real dashboard remediation run
- [x] document the rollout model that keeps direct Sonar remediation only as a
      temporary fallback until dashboard-backed remediation is stable
- [x] document that Sonar dashboard sync remains the active discovery producer
      for Sonar-derived dashboard items while the old direct Sonar remediation
      path is being deprecated
- [x] review and update the existing Sonar dashboard sync behavior, tests, and
      operator guidance where needed so it remains a reliable producer for the
      dashboard-backed remediation flow, including keeping cleanup limited to
      stale untouched `open` Sonar items instead of rewriting remediation-owned
      lifecycle states
- [x] move the dashboard remediation execution core from fabricated
      `SonarIssue` inputs to a remediation-native execution contract
- [x] adapt the legacy direct Sonar remediation path into
      `RemediationWorkItem` so both paths converge on the same execution model
- [x] treat Sonar-specific prompting and execution policy as one producer
      profile instead of the default runtime contract
- [x] decide which generic remediation work-item fields are true execution
      inputs in v1 and either honor them explicitly or document them as
      pass-through metadata only, with `constraints` as the only new runtime
      execution input and the remaining generic fields kept as pass-through
      metadata for now
- [x] document that outcome comparison against the old direct Sonar path is an
      ongoing rollout and operational validation activity rather than a
      remaining implementation blocker for the remediation workflow itself
- [x] define and validate how dashboard write conflicts or stale remote state
      are retried or failed safely during rollout
- [x] surface stale `in_progress` recovery clearly in the final run summary as
      well as in the dashboard item log

Done when:

- one supported dashboard item can produce the same quality merge request as
      the direct Sonar path
- failed dashboard remediation attempts leave both the repository and dashboard
      in predictable states
- stale `in_progress` recovery and dashboard write-conflict behavior are proven
      in real workflow tests or smoke runs
- operators have a documented rollout path for validating dashboard-backed
      remediation before retiring the old direct Sonar runner
- dashboard-backed remediation execution no longer depends on rebuilding fake
      Sonar issues for supported dashboard items
- direct Sonar and dashboard-backed remediation share the same
      remediation-native execution contract during the deprecation window
- the roadmap and operator story stay clear that Sonar dashboard sync continues
      to own discovery for Sonar-derived items even after direct Sonar
      remediation is retired
- the Sonar dashboard sync path remains intentionally maintained as the
      discovery/update mechanism for Sonar-derived dashboard items during the
      remediation migration
- Sonar dashboard sync cleanup remains limited to stale untouched `open`
      Sonar items so remediation-owned lifecycle history is preserved once work
      has started

### Pre-Demo Phase 6: Reconciliation Design

Goal:

- design the scheduled reconciliation workflow needed to close the dashboard
      lifecycle loop before product demonstration
- keep remediation implementation complete while making post-MR state
      transitions explicit and reviewable

Status:

- [ ] define when scheduled reconciliation runs and which dashboard item states
      it owns
- [ ] define transition rules for `mr_opened -> done`, `mr_opened -> open`, and
      any explicit failure state used after merge request closure
- [ ] define how reconciliation handles merge requests that are missing,
      manually edited, or no longer match stored branch and commit metadata
- [ ] define how reconciliation cooperates with the existing stale
      `in_progress` recovery rule without overlapping ownership
- [ ] update the functional and technical design docs once the reconciliation
      workflow contract is agreed

Done when:

- the product has an explicit design for how dashboard items leave
      `mr_opened` after merge request outcomes are known
- operators can understand which workflow owns active remediation transitions
      and which workflow owns later merge request convergence
- reconciliation is ready to move from design into implementation without
      reopening the remediation workflow architecture

### Post-Remedy Phase 11: CI/CD And Security Hardening

Goal:

- improve release reliability, workflow safety, and supply-chain hygiene after
  dashboard-backed remediation is implemented

Status:

- [ ] harden GitHub release-to-GHCR publishing so tag and release mismatches are
      easier to detect and recover from
- [ ] review GitLab CI examples and workflow permissions for least-privilege
      token usage
- [ ] document secret usage boundaries for `GITLAB_TOKEN`,
      `RELEASE_PLEASE_TOKEN`, and `OPENAI_API_KEY`
- [ ] add focused smoke or regression checks for release and image publish
      behavior
- [ ] review container publish and example pipeline behavior for failure cases
- [ ] add a prerelease or release-candidate image publish path so CLI, CI, and
      dashboard changes can be tested before a stable release
- [ ] keep dependency and container security guidance current alongside
      `pip-audit`
- [ ] add a staged security-tool rollout plan:
      dependency scanning now, one Python-focused SAST tool next, then
      container/base-image scanning once CI noise is acceptable

Done when:

- release creation and image publication failures are easier to diagnose and
  recover from
- CI examples reflect the minimum required permissions clearly
- security-sensitive tokens have explicit documented roles
- workflow and image publish regressions are more likely to be caught before a
  broken release reaches operators
- candidate images can be tested in real GitLab pipelines before promoting a
  stable release
- security tooling is introduced gradually enough to keep CI signal usable

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
