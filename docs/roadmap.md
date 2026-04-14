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
- [x] consolidate operator-facing example files into a dedicated `examples/`
      layout so setup templates are easier to discover and copy safely

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

## Completed Follow-Up Phase

### Dashboard Review Feedback And Retry-State

Completed summary:

- linked remediation MR reviews back onto their remediation dashboard items
- surfaced compact review state and retry state directly in the dashboard
- made reconciliation the owner of bounded retry eligibility decisions
- let remediation consume bounded prior review feedback without collapsing
  review, reconciliation, and remediation responsibilities together

Design references:

- [functional-design-dashboard-review-feedback.md](functional-design-dashboard-review-feedback.md)
- [technical-design-dashboard-review-feedback.md](technical-design-dashboard-review-feedback.md)

## Next Review Follow-Up Phase

### Incremental PR Review Memory

Goal:

- make repeated reviews on the same merge request feel incremental rather than
  stateless
- reduce repeated comments after new commits while keeping the current diff and
  code as the primary evidence surface

Design references:

- [functional-design-pr-review-memory.md](functional-design-pr-review-memory.md)
- [technical-design-pr-review-memory.md](technical-design-pr-review-memory.md)
- [functional-design-pr-review-followup-reconciliation.md](functional-design-pr-review-followup-reconciliation.md)
- [technical-design-pr-review-followup-reconciliation.md](technical-design-pr-review-followup-reconciliation.md)
- [functional-design-pr-review-stable-finding-identity.md](functional-design-pr-review-stable-finding-identity.md)
- [technical-design-pr-review-stable-finding-identity.md](technical-design-pr-review-stable-finding-identity.md)

#### Phase 1: Persist Bounded Prior Review Passes

Goal:

- extend review state so repeated reviews can reuse compact structured prior
  bot review history

Status:

- [x] persist bounded prior review passes keyed by MR IID and reviewed SHA
- [x] store prior review classification, findings count, short summary, and
      bounded normalized findings
- [x] bound stored history by `review.max_prior_review_passes`
- [x] add regression coverage for state persistence and trimming

Done when:

- review state stores enough structured history for later review passes
- history stays bounded and deterministic
- the first storage path does not depend on parsing rendered GitLab notes

#### Phase 2: Load Prior Review Context Into Analysis

Goal:

- load compact prior review memory for the same MR and include it in the next
  review analysis prompt

Status:

- [x] load prior bot-authored review history for the current MR from persisted
      state
- [x] inject bounded prior review context into prompt construction
- [x] keep `review.max_prior_review_passes` configurable with a conservative
      default of `2`
- [x] add prompt and service coverage for no-history and repeated-review cases

Done when:

- repeated reviews on the same MR receive bounded prior review memory as prompt
  context
- current diff and code remain the primary evidence surface
- history loading stays same-MR-only and bot-authored-only

#### Phase 3: Incremental Review Output Framing

Goal:

- make repeated bot reviews feel like follow-up passes instead of fresh
  discoveries

Status:

- [x] add light follow-up framing for unresolved earlier findings
- [x] allow concise "no new actionable findings since the last reviewed SHA"
      language when appropriate
- [x] avoid repeating unchanged earlier findings as if they were newly
      discovered
- [x] add regression coverage for repeated-finding and no-new-finding phrasing

Done when:

- repeated reviews read like incremental follow-up notes
- unresolved earlier findings are framed as follow-up context rather than fresh
  discoveries
- output stays concise and trust-building instead of turning into history recap

#### Phase 4: Live Testing And Feedback Tightening

Goal:

- validate the first review-memory behavior against real merge request updates
  before adding more policy or feedback mechanisms

Status:

- [ ] collect repeated-review examples where new commits previously caused bot
      repetition
- [ ] compare repeated-review notes before and after prior-review memory
- [ ] refine lightweight follow-up phrasing only from real examples
- [ ] decide whether any later operator feedback loop is needed beyond bounded
      same-MR memory

Done when:

- repeated-review noise is lower on real merge requests with new commits
- the bot clearly distinguishes new findings from unresolved earlier ones
- follow-up phrasing feels natural enough in real review notes without opening
  a larger redesign

### Follow-Up Review Outcome Reconciliation

Goal:

- make repeated reviews explicitly acknowledge whether earlier concerns still
  appear unresolved, now appear resolved, or have been replaced by different
  new concerns
- make repeated MR reviews feel more like a conversation than a stateless rerun

Design references:

- [functional-design-pr-review-followup-reconciliation.md](functional-design-pr-review-followup-reconciliation.md)
- [technical-design-pr-review-followup-reconciliation.md](technical-design-pr-review-followup-reconciliation.md)

#### Phase 1: Conservative Finding Matching

Goal:

- derive a bounded internal comparison between the latest prior review pass and
  the current findings

Status:

- [x] compare only against the latest prior review pass for the same MR
- [x] match findings conservatively using file path, title, and normalized summary
- [x] classify matches as `still_unresolved`, `appears_resolved`, or `new`
- [x] add regression coverage for repeated, resolved, and new-finding cases

Done when:

- the review workflow can derive a compact follow-up comparison result without
  adding a large new schema
- matching stays conservative and deterministic

#### Phase 2: Conversational Follow-Up Wording

Goal:

- make repeated review notes acknowledge progress or non-progress more clearly

Status:

- [x] render `still unresolved` wording for repeated matched findings
- [x] render `appears resolved` wording when prior findings disappear and the
      visible code supports that conclusion
- [x] render a short mixed follow-up line when an earlier concern appears
      resolved but a different new concern now appears
- [x] mention resolved earlier findings in both `no_findings` and mixed
      new-finding follow-ups when that improves continuity

Done when:

- repeated reviews clearly distinguish unresolved, resolved, and new concerns
- note wording feels more like a continued thread than a fresh review each time

#### Phase 3: Ambiguity And Trust Guardrails

Goal:

- keep the new follow-up continuity helpful without overclaiming resolution

Status:

- [x] fall back to neutral follow-up wording when finding matching is weak
- [x] use explicit `unable to verify` wording when current code does not
      reliably support a resolved conclusion
- [x] avoid strong resolved wording when the visible code remains ambiguous
- [x] add regression coverage for ambiguous follow-up cases

Done when:

- the bot does not overstate that a prior issue is fixed when the current code
  does not support that claim
- follow-up notes stay trust-building in ambiguous cases

#### Phase 4: Live Testing And Wording Tightening

Goal:

- validate the conversational follow-up behavior on real merge-request review
  threads

Status:

- [ ] collect real sequences with first finding, repeated finding, and resolved
      finding outcomes
- [ ] compare whether operators perceive the new follow-up notes as more
      conversational and trustworthy
- [ ] tighten wording only from real examples, not theoretical cases
- [ ] decide whether a later explicit finding fingerprint or richer relationship
      schema is actually needed

Done when:

- repeated review threads feel more conversational in live use
- resolved earlier concerns are acknowledged clearly enough to improve operator
  trust
- the current simple matching approach is either proven sufficient or clearly
  bounded for a later follow-up

### Stable Finding Identity For Follow-Up Matching

Goal:

- move repeated-review reconciliation onto a more stable machine-facing finding
  identity
- reduce dependence on human title wording for follow-up matching
- preserve conversational MR notes while making matching more deterministic

Design references:

- [functional-design-pr-review-stable-finding-identity.md](functional-design-pr-review-stable-finding-identity.md)
- [technical-design-pr-review-stable-finding-identity.md](technical-design-pr-review-stable-finding-identity.md)

#### Phase 1: Persist Canonical Finding Identity

Goal:

- extend persisted prior review finding state with a canonical machine identity

Status:

- [ ] add optional stored `identity` field for persisted prior review findings
- [ ] derive the identity in application code from normalized file path and
      normalized issue subject
- [ ] keep the first identity shape as one canonical stored string
- [ ] preserve current human-facing summary storage alongside the new identity

Done when:

- new persisted review findings store both machine identity and human summary
- the first identity shape is deterministic, conservative, and test-covered

#### Phase 2: Load Identity Into Prior Review Context

Goal:

- make stable finding identity available during repeated-review reconciliation

Status:

- [ ] extend prior review loading to carry stored identity into the review
      workflow
- [ ] preserve backward compatibility for older entries that do not have
      identity
- [ ] avoid migration or backfill requirements for the first rollout
- [ ] add regression coverage for mixed old/new persisted review history

Done when:

- repeated-review context can use stable identity when it exists
- older persisted entries still load safely through legacy state handling

#### Phase 3: Prefer Identity-First Reconciliation

Goal:

- make follow-up matching depend primarily on stored machine identity instead
  of title drift

Status:

- [ ] update follow-up reconciliation to match exact identity first
- [ ] reserve legacy summary/title fallback for older entries without identity
- [ ] keep ambiguity guardrails and conservative trust wording intact
- [ ] add regression coverage for wording-drift cases that should now reconcile
      through stable identity

Done when:

- same-issue follow-up matching is driven primarily by stored identity
- title-overlap heuristics are no longer the main path for new persisted entries

#### Phase 4: Live Testing And Collision Review

Goal:

- validate that the first identity shape is stable enough in real repeated
  review threads without collapsing unrelated same-file findings together

Status:

- [ ] collect live examples where stable identity improves continuity
- [ ] watch for same-file collision cases or over-broad identity matches
- [ ] refine normalization only from real examples
- [ ] decide whether the first identity shape is sufficient or needs a later
      narrower subject model

Done when:

- repeated-review matching is more reliable in live usage
- no meaningful collision pattern is observed, or a bounded next refinement is
      clearly identified

## Beyond V1

Post-v1 ideas and expansion tracks now live in
[future_plans.md](future_plans.md).

That includes:

- dashboard-centered review feedback and retry-state design
  - [functional-design-dashboard-review-feedback.md](functional-design-dashboard-review-feedback.md)
  - [technical-design-dashboard-review-feedback.md](technical-design-dashboard-review-feedback.md)
- incremental PR review memory design
  - [functional-design-pr-review-memory.md](functional-design-pr-review-memory.md)
  - [technical-design-pr-review-memory.md](technical-design-pr-review-memory.md)
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
