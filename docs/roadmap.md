# ZeroOne Ops Roadmap

## Purpose

This roadmap translates the current functional and technical design into an
implementation sequence for v1 of the broader ZeroOne Ops platform.

The repository and runtime still use the compatibility name `ai-sonar-bot`,
but the roadmap now reflects a product scope that includes review,
dashboard-backed remediation, and reconciliation rather than only SonarQube
automation.

It is intentionally short and execution-focused. The goal is to make the next steps obvious and keep scope controlled while the bot is being built.

Working rule:

- after each meaningful implementation round, pause for a short cleanup review
  before starting the next feature slice
- use that review to check workflow boundaries, growing files/services, test
  gaps, and any documentation drift created by the last round

Next sequencing note:

- after the current feature-building phase, shift into a dedicated hardening
  and testing phase before starting any new operator-experience or onboarding
  work
- once the workflows are stable under real usage, treat ease of operation as
  the next product phase

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

### Completed Build: Review Bot Improvements

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
- [x] add advisory `review_confidence` and `review_confidence_reason` so the
      review bot exposes a clear operator trust signal without becoming a gate
- [x] make manual-review-only outcomes clearer so operators can distinguish
      insufficient context from low-value findings
- [x] add repo-level controls for review noise such as path filtering,
      changed-file limits, and note verbosity
- [x] teach the review bot to discover bounded repository guidance such as
      `AGENT.md`, engineering standards, and relevant technical design docs in
      the repository it is reviewing

Done when:

- review notes feel conservative, evidence-backed, and useful in real merge
      request workflows
- remediation-authored merge requests get richer review quality without making
      review dependent on bot-authored changes

### Current Phase: Review Bot Live Testing

Goal:

- run the review bot in real merge request workflows for a sustained period
- capture missed findings, noisy findings, and operator friction before opening
  another review feature phase

Status:

- [ ] collect real review examples where the bot was too conservative or too
      noisy
- [x] tighten the review prompt so deterministic runtime errors, invalid
      operations, and harmful debug code are treated as actionable even when
      they are subtle
- [ ] convert incorrect, noisy, or missed review outcomes into targeted
      regression tests
- [ ] decide from live feedback whether the current no-findings bias should be
      relaxed so grounded medium-confidence findings can still be reported
- [ ] document any recurring review patterns that should become prompt,
      validation, or ranking follow-up work after the live-testing period

Done when:

- the team has a representative set of live review outcomes to evaluate
- the first batch of real review misses and false positives has been turned
      into regression coverage
- the next review iteration is driven by observed behavior rather than
      speculative tuning

### Interim Phase: Pre-Release Candidate Hardening

Goal:

- keep progress moving while feature testing is underway without opening new
  large workflow scope
- strengthen rollout safety and operator confidence around the existing
  workflows
- prepare the release, image, and docs surface for the `ZeroOne Ops` rebrand
  without destabilizing runtime compatibility during the testing week

Status:

- [ ] harden CI/CD behavior around schedules, failure visibility, and operator
      guidance where testing reveals rough edges
- [x] review GitLab job defaults, resource groups, and dry-run/live boundaries
      for the shipped workflows
- [x] tighten auth and secret-handling documentation where operator setup is
      still easy to misconfigure
- [x] add a conservative Renovate setup for dependency management so CI and
      dependency drift stay under control during the hardening period
- [x] add a conservative security scanning layer with `pip-audit` and
      `Bandit`, keeping the current rollout advisory and low-noise
- [x] add a prerelease or release-candidate image publish path so CLI, CI, and
      dashboard changes can be tested before a stable release
- [x] add a lightweight prerelease image smoke test so the published container
      is validated with a small real command surface before broader rollout
- [x] complete a secret and logging safety audit
- [x] add a small release checklist covering image publish, CI setup, auth
      readiness, smoke-test status, and known rollout issues

Done when:

- CI/CD guidance feels stable enough for repeated operator use during the
      hardening period
- dependency updates are easier to review and less likely to pile up while the
      workflows are being stabilized
- basic security scanning is present in CI with acceptable signal-to-noise
      before any stronger enforcement is considered
- operators have a safe way to test near-production image changes before stable
      release tags are cut
- the release path has a lightweight repeatable checklist and smoke test rather
      than relying only on ad hoc confidence
- any rollout friction found during testing has a clear documented home and,
      where needed, a small fix

### Rebrand Phases

Goal:

- move the product toward `ZeroOne Ops` with one deliberate naming plan instead
  of a series of partial renames
- update outward-facing identity first while keeping runtime compatibility
  stable during the current testing period

#### Phase 1: Brand Decision

Status:

- [x] confirm `ZeroOne Ops` as the product name
- [x] confirm `zeroone-ops` as the technical slug for release and packaging
- [x] define `ai-sonar-bot` as the temporary runtime compatibility name for the
      CLI, package path, config filename, and filesystem paths until a later
      dedicated runtime rename phase

#### Phase 2: Publish And Release Rebrand

Status:

- [x] update release tags, release-please naming, and published image naming to
      `zeroone-ops`
- [x] keep legacy release tag handling long enough to avoid breaking current
      manual release flows
- [x] update publish workflow docs and retry instructions to the new release
      slug

#### Phase 3: Docs And Product Surface

Status:

- [x] rebrand README, roadmap, changelog framing, and runbook headings to
      `ZeroOne Ops`
- [x] add one short transition note that explains brand name versus temporary
      compatibility names
- [x] update operator-facing examples that should show the new image and release
      names

#### Phase 4: Operator Surface

Status:

- [x] update GitLab CI example image references and onboarding instructions to
      the new published image name
- [x] review release instructions, smoke-test guidance, and workflow setup docs
      for old-name drift
- [x] keep runtime commands stable where changing them would add operator risk
      during testing

#### Phase 5: Runtime Rename (Later)

Status:

- [ ] decide after the testing week whether to rename the CLI command, Python
      package path, config filename, env vars, `/opt/ai-sonar-bot`, and GitLab
      job identifiers
- [ ] if a runtime rename happens, support both old and new config naming
      temporarily and document the deprecation path

Done when:

- the project has one clear brand and one clear technical slug
- release, image, and docs surfaces consistently use the new name
- compatibility names are temporary, documented, and not mistaken for the
      preferred public identity
- runtime rename work, if still desired, has a dedicated later phase rather
      than being mixed into the current hardening work

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

- dashboard-centered review feedback and retry-state design
  - [functional-design-dashboard-review-feedback.md](functional-design-dashboard-review-feedback.md)
  - [technical-design-dashboard-review-feedback.md](technical-design-dashboard-review-feedback.md)
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
