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

Current execution model:

- the project is now in an ongoing testing window with two parallel tracks:
  review bot live testing and rollout/CI hardening
- keep feature expansion constrained while those tracks absorb real usage
  feedback
- once the workflows are stable under repeated operator use, treat ease of
  operation and dashboard-centered review feedback as the next product phase

## Current Status

Current focus:

- ongoing track 1: review bot live testing
- ongoing track 2: rollout and CI hardening during testing
- next follow-up phase after the testing window: dashboard-centered review
  feedback and retry-state work

Finished foundation:

- core functional and technical design
- local quality tooling, architecture checks, and GitHub Actions quality
  workflow
- remediation execution stack: intake, analysis, patching, git automation,
  merge request creation, CI mode, and richer failure logging
- runner and service refactors that moved workflow orchestration into clearer
  dedicated homes

## Finished Phases

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

- merge request intake, selection, dedup, and bounded diff/context building
- structured review analysis with deterministic note publishing and persisted
  review state
- CLI and shared-image integration, operator docs, and smoke-test guidance
- baseline hardening for no-findings, findings-present, and unchanged-SHA skip

Design references:

- [functional-design-pr-review.md](docs/functional-design-pr-review.md)
- [technical-design-pr-review.md](docs/technical-design-pr-review.md)

### Runner Cleanup

Completed summary:

- `runner.py` reduced to a thin composition and delegation layer
- remediation, reconciliation, and review orchestration moved into dedicated
  runner services
- regression coverage preserved CLI-facing summaries and failure behavior while
  tightening workflow boundaries

### Review Bot Improvements

Completed summary:

- review prompt and validation hardened against speculative findings,
  unsupported evidence, and untrusted MR input
- advisory confidence, manual-review-only clarity, and repo-level noise
  controls added
- remediation-authored MR context and bounded repository guidance discovery now
  improve review quality without coupling review to bot-authored changes

## Current Testing Tracks

The project is now in a sustained testing and hardening window with two
parallel tracks rather than one linear implementation phase.

### Track 1: Review Bot Live Testing

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

### Track 2: Pre-Release Candidate Hardening During Testing

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

## Rebrand Status

Goal:

- move the product toward `ZeroOne Ops` with one deliberate naming plan instead
  of a series of partial renames
- update outward-facing identity first while keeping runtime compatibility
  stable during the current testing period

Completed:

- `ZeroOne Ops` adopted as the product name and `zeroone-ops` as the technical
  release and packaging slug
- publish, release, docs, and operator-facing surfaces moved to the new public
  name
- temporary runtime compatibility names retained where changing them would add
  testing risk

Later:

- decide after the testing window whether to rename the CLI command, Python
  package path, config filename, env vars, `/opt/ai-sonar-bot`, and GitLab job
  identifiers
- if a runtime rename happens, support both old and new config naming
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

## Next Follow-Up Phase

### Dashboard Review Feedback And Retry-State

Goal:

- make the dashboard the canonical machine-readable record for remediation
  review outcomes
- keep MR notes as the operator-facing review surface
- prepare a conservative retry loop without introducing an unbounded cycle

Design references:

- [functional-design-dashboard-review-feedback.md](functional-design-dashboard-review-feedback.md)
- [technical-design-dashboard-review-feedback.md](technical-design-dashboard-review-feedback.md)

#### Phase 1: Dashboard Review State Linkage

Goal:

- link reviewed remediation MRs back to their remediation dashboard items
- attach lightweight structured review metadata to the remediation item
- keep standalone `review_status` items only as fallback for non-remediation
  reviews

Status:

- [ ] extend the dashboard item model with the first bounded review metadata
      fields
- [ ] teach the review dashboard updater to enrich linked remediation items
- [ ] keep fallback behavior for human-authored MRs with no remediation item
- [ ] add tests for deterministic MR-to-dashboard linking

Done when:

- a reviewed remediation MR updates the linked remediation item with
  structured review state
- fallback review mirroring still works for non-remediation MRs
- link failures are explicit and test-covered

#### Phase 2: Dashboard Rendering And Operator Visibility

Goal:

- make linked review state visible on remediation items without relying on raw
  JSON details
- improve operator visibility into whether a remediation MR was reviewed and
  what happened

Status:

- [ ] render compact review state on remediation items
- [ ] show findings count, review status, reviewed SHA, and short summary or
      block reason
- [ ] add renderer and parser coverage for the new fields

Done when:

- operators can answer review-state questions directly from the dashboard
- failed or reopened remediation items visibly preserve their linked review
  context

#### Phase 3: Reconciliation-Derived Retry Eligibility

Goal:

- let reconciliation preserve review state across lifecycle transitions
- derive bounded retry eligibility from structured review outcome, traceability,
  and retry limits

Status:

- [ ] preserve review metadata when reconciliation marks items `done`,
      reopens them, or moves them to `failed`
- [ ] add `retry_count`, `retry_eligible`, and `retry_block_reason`
- [ ] derive retry eligibility in reconciliation instead of in the review
      workflow
- [ ] keep the first retry model conservative with a default limit of `1`,
      configurable in JSON

Done when:

- reopened or failed remediation items retain their linked review state
- retry eligibility is visible, bounded, and test-covered
- reconciliation owns retry eligibility decisions without taking over review
  judgment or remediation execution

#### Phase 4: Retry-Aware Remediation Consumption

Goal:

- allow a later remediation attempt to consume bounded prior review feedback as
  structured machine context
- keep retry execution in remediation while preserving the ownership
  boundaries

Status:

- [ ] extend remediation context building with bounded prior review feedback
- [ ] increment retry counters only when a real retry starts
- [ ] block retries cleanly when traceability or review signal is too weak
- [ ] add regression coverage for one bounded retry path

Done when:

- a retrying remediation attempt can use prior structured review context
  without relying on raw MR note prose
- retry counts stay bounded and operator-auditable
- the first retry loop is conservative, deterministic, and easy to explain

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
