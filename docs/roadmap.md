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

- [ ] the main execution path is covered by tests
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

- [functional-design-pr-review.md](/Users/justinmelger/Desktop/github/ai-sonar-bot/docs/functional-design-pr-review.md)
- [technical-design-pr-review.md](/Users/justinmelger/Desktop/github/ai-sonar-bot/docs/technical-design-pr-review.md)

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

- [ ] add review-specific finding/result models
- [ ] add `ReviewAnalysisService`
- [ ] validate LLM output shape before publishing

Done when:

- the LLM returns structured review results
- malformed or oversized review outputs are rejected
- the bot can classify review results deterministically

### Review Phase 5: Review Note Publishing

Goal:

- publish one deterministic merge request note
- keep output readable and non-spammy

Status:

- [ ] add `ReviewPublisher`
- [ ] render one deterministic summary note template
- [ ] support both findings-present and no-findings note shapes

Done when:

- the bot can publish one MR note through GitLab
- findings are formatted consistently
- no-findings output is distinguishable from failure to review

### Review Phase 6: Review State and Runner Integration

Goal:

- persist review outcomes
- wire the review workflow into the shared CLI and state system

Status:

- [ ] add review state records keyed by MR IID and head SHA
- [ ] add a review runner path and CLI subcommand
- [ ] keep the review workflow in the shared image with separate commands

Done when:

- review outcomes are persisted in state
- the CLI can run the review workflow explicitly
- the shared image can execute either Sonar remediation or PR review

### Review Phase 7: Hardening

Goal:

- make the review bot usable in real GitLab workflows
- keep reviews useful and low-noise

Status:

- [ ] add tests for no-findings and findings-present review paths
- [ ] add integration coverage for unchanged-SHA skip
- [ ] document operator usage and rollout expectations
- [ ] add a smoke-test recipe for one real merge request review run

Done when:

- the bot avoids duplicate notes for unchanged MR revisions
- the review note format is stable and readable
- another engineer can run and validate the review bot from docs alone

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
