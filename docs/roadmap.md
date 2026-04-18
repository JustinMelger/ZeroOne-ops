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
- next planned review-context phase after the current testing window:
  function-aware review context, subject to results from live helper-following
  testing
- separate post-testing operator track: dashboard readability and workflow
  cleanup for remediation/reconciliation use

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

Alongside those tracks, we can also take on bounded support work that improves
workflow continuity without changing review-bot judgment, such as MR-scoped
operator feedback intake for repeated reviews.

### Parallel Continuity Plan

Goal:

- stabilize repeated-review continuity before adding MR-scoped operator
  feedback intake
- improve continuity using both stronger benchmark coverage and a cleaner
  review-versus-overlap architecture

Planned order:

1. Continuity benchmark track

- add more multi-pass review continuity regression fixtures like the current
  `ValueError` sequence
- cover wording drift, removed-versus-new concern swaps, and nearby
  sibling/helper continuity cases
- keep these fixtures focused on reconciliation behavior so they stay fast and
  deterministic

2. Stability track

- strengthen app-side overlap candidate generation using canonical identity,
  legacy identity, structured fields, and bounded summary/title fallback
- add clearer ambiguous-overlap handling so weak matches fall back to neutral
  continuity rather than overclaiming sameness or resolution
- keep layered matching as the baseline rather than trying to replace it with a
  single key

Current implementation note: Phase 1 `Continuity Stability Tightening`

Scope:
- strengthen candidate generation and bounded matcher behavior using the new
  continuity benchmark suite
- tighten mixed structured/unstructured fallback rules without regressing
  sibling, ambiguity, or cross-file separation
- treat the benchmark suite as the main regression gate for continuity changes

Out of scope:
- no second LLM overlap pass yet
- no MR-scoped operator feedback intake yet
- no broad natural-language similarity layer

Stable-enough gate before moving to the architecture track:
- continuity benchmark fixtures pass consistently
- mixed structured/unstructured wording drift behaves reliably enough
- sibling and ambiguous same-file cases do not regress into false merges
- remaining continuity misses are architectural enough to justify the split

3. Architecture track

- split current-pass review from bounded overlap reconciliation
- let the first pass find current findings only
- let the second pass compare current findings to prior findings within an
  app-prepared candidate set
- keep final persisted identity and state application app-owned

4. Operator feedback gate

- only implement MR-scoped structured operator feedback intake after the main
  continuity benchmark cases feel stable enough in live and regression testing
- use the continuity benchmark cases as the readiness signal before enabling
  feedback-driven repeated-review behavior

### Track 1: Review Bot Live Testing

Goal:

- run the review bot in real merge request workflows for a sustained period
- capture missed findings, noisy findings, and operator friction before opening
  another review feature phase

Status:

- [ ] collect real review examples where the bot was too conservative or too
      noisy
- [ ] validate shipped helper-following context against live review examples
      and collect any remaining misses it does not yet cover
- [ ] validate shipped function-aware context against live review examples on
      long Python functions and collect any remaining misses it does not yet
      cover
- [ ] collect operator feedback on note clarity, trust, and actionability in
      day-to-day review use
- [ ] clarify operator-facing JSON expectations where it is currently unclear
      which fields are required versus optional
- [x] document the current trust-first judgment strategy so prompt tuning and
      later context-expansion work use the same policy baseline
- [x] tighten the review prompt so deterministic runtime errors, invalid
      operations, and harmful debug code are treated as actionable even when
      they are subtle
- [ ] convert incorrect, noisy, or missed review outcomes into targeted
      regression tests
- [ ] decide from live feedback whether the current no-findings bias should be
      relaxed so grounded medium-confidence findings can still be reported
- [ ] document any recurring review patterns that should become prompt,
      validation, or ranking follow-up work after the live-testing period
- [ ] document recurring operator friction in triaging, interpreting, and
      acting on review output
- [ ] add MR-scoped structured operator feedback intake for review findings
      so developers can mark a numbered finding as invalid, accepted, or
      unclear without changing review analysis behavior
- [ ] wire review reconciliation to consume that MR-scoped feedback on later
      passes of the same merge request

Done when:

- the team has a representative set of live review outcomes to evaluate
- the first batch of real review misses and false positives has been turned
      into regression coverage
- operator-facing trust and usability feedback has been collected alongside
      raw review-quality feedback
- the next review iteration is driven by observed behavior rather than
      speculative tuning

Reference:

- [review-bot-judgment-strategy.md](docs/review-bot-judgment-strategy.md)

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
- prioritize the repository config filename in that decision, because
  `.ai-sonar-bot.json` is still operator-facing and now reads as a misleading
  legacy name
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

## Next Operator Workflow Phase

### Dashboard Readability And Workflow Cleanup

Goal:

- improve the operator experience for remediation and reconciliation workflows
  now that the core bot behavior is proving useful in the test repository
- make the dashboard and linked MR surfaces easier to scan quickly without
  reopening workflow logic

Likely direction:

- simplify dashboard status presentation so operators do not need to scan
  multiple separate status tables for the same workflow
- evaluate moving toward one overview table with a clear `status` column unless
  a separate section is truly needed for operator action
- tighten MR/dashboard information hierarchy so the most important state,
  outcome, and next-action signals are easier to find

Start after:

- the current review-bot testing window has produced enough confidence that the
  main remaining friction is operator-surface readability rather than workflow
  correctness

Done when:

- operators can scan remediation and reconciliation state quickly in one pass
- dashboard layout reflects real operator workflow better than the current
  status-silo presentation
- any small MR/dashboard presentation cleanup stays scoped and does not reopen
  the core remediation/reconciliation logic

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

## Completed Review Follow-Up Work

Completed summary:

- bounded prior review memory is now persisted and loaded for same-MR follow-up
  passes
- repeated review notes can acknowledge unresolved, resolved, and new concerns
  more conversationally without treating each run as stateless
- helper-following review context is implemented for bounded same-file Python
  helpers and is now available as supporting context during review

Still being validated in the current testing window:

- how well repeated-review continuity holds up on real merge-request threads
- how much helper-following reduces call-site-only false positives in practice
- whether imported-helper following is worth a later slice

Design references:

- [functional-design-pr-review-memory.md](functional-design-pr-review-memory.md)
- [technical-design-pr-review-memory.md](technical-design-pr-review-memory.md)
- [functional-design-pr-review-followup-reconciliation.md](functional-design-pr-review-followup-reconciliation.md)
- [technical-design-pr-review-followup-reconciliation.md](technical-design-pr-review-followup-reconciliation.md)
- [functional-design-pr-review-stable-finding-identity.md](functional-design-pr-review-stable-finding-identity.md)
- [technical-design-pr-review-stable-finding-identity.md](technical-design-pr-review-stable-finding-identity.md)
- [functional-design-pr-review-structured-reconciliation.md](functional-design-pr-review-structured-reconciliation.md)
- [technical-design-pr-review-structured-reconciliation.md](technical-design-pr-review-structured-reconciliation.md)
- [functional-design-pr-review-helper-following-context.md](functional-design-pr-review-helper-following-context.md)
- [technical-design-pr-review-helper-following-context.md](technical-design-pr-review-helper-following-context.md)

## Next Review Context Phase: Function-Aware Review Context

Current state:

- core implementation is shipped
- remaining work is live validation, example collection, and one bounded
  follow-up pass only if testing shows a repeated gap

Design references:

- [functional-design-pr-review-function-aware-context.md](functional-design-pr-review-function-aware-context.md)
- [technical-design-pr-review-function-aware-context.md](technical-design-pr-review-function-aware-context.md)

### Phase 1: Config And Boundary Detection

Goal:

- add the function-aware config knobs and implement AST-first enclosing
  function boundary detection for Python files

Status:

- [x] add function-aware review config flags and limits
- [x] detect the enclosing Python function for a changed hunk using AST
- [x] fall back safely when parsing fails or no enclosing function is found

Done when:

- review config can enable/disable function-aware context explicitly
- the builder can detect enclosing Python function bounds deterministically
- unsupported or uncertain cases stay on the existing hunk-window path

### Phase 2: Bounded Function Context Expansion

Goal:

- expand changed-file review context to the enclosing Python function when it
  fits within bounded limits

Status:

- [x] keep the current fixed hunk window as the baseline
- [x] expand to whole-function context when the enclosing function fits within
      the configured line limit
- [x] preserve deterministic `start_line`, `end_line`, and `truncated`
      behavior

Done when:

- small and medium Python functions can be included whole
- non-Python files continue using the current bounded window logic
- prompt context remains bounded and deterministic

### Phase 3: Large-Function Clipping

Goal:

- support long Python functions without allowing function-aware context to
  consume the whole prompt

Status:

- [x] add bounded clipping for oversized enclosing functions
- [x] keep the function signature visible in clipped output
- [x] keep the changed hunk and nearby lines visible in clipped output

Done when:

- large Python functions produce a deterministic clipped function-aware slice
- the clipped output still keeps the signature and changed hunk visible
- oversized functions remain marked as truncated

### Phase 4: Testing And Tightening

Goal:

- validate that function-aware expansion improves long-function review quality
  without bloating prompts unnecessarily

Status:

- [x] add deterministic tests for whole-function inclusion, non-Python
      fallback, and large-function clipping
- [ ] collect live examples where function-aware expansion improves review
      accuracy on long legacy methods
- [ ] decide whether the current function-aware limits are sufficient or need
      later adjustment

Done when:

- function-aware context is covered by deterministic tests
- live review examples show better handling of long changed functions
- the team has enough evidence to keep the current limits or make one bounded
      follow-up adjustment

## Shipped Review Context Improvements Under Live Validation

These context-expansion tracks are no longer primarily design work. The core
implementation is shipped, and the current phase is live validation rather
than broadening scope immediately.

### Helper-Following Context

Current implementation:

- same-file direct helper functions
- same-file conservative methods such as `self.foo()`, `cls.foo()`, and
  `ClassName.foo()`
- one-hop project-local imported helper functions
- bounded helper counts and line budgets
- supporting-context prompt rendering and optional diagnostics

Current phase:

- live testing
- collecting review examples that confirm improvement or expose remaining
  misses
- deciding whether a later bounded follow-up is needed for diagnostics or
  additional safe resolution cases

### Function-Aware Context

Current implementation:

- Python AST-based enclosing function detection
- whole-function expansion when the function fits the configured limit
- bounded clipped rendering for large functions, keeping the function opening
  and changed hunk visible
- deterministic tests for whole-function, fallback, and clipping behavior

Current phase:

- live testing
- collecting review examples on long-function code
- deciding whether the current clipping and line limits are sufficient or need
  one bounded follow-up adjustment

## Next Review Continuity Phase: Stable Identity And Reconciliation

Current state:

- bounded prior review memory, stable persisted finding identity, and
  identity-first follow-up wording are shipped
- repeated-review continuity still depends too much on wording drift in real
  use
- the more stable next step is stronger machine-facing identity and
  reconciliation infrastructure

Goal:

- make repeated review continuity less dependent on human wording
- improve `still unresolved`, `appears resolved`, and `new issue` follow-up
  behavior on repeated MR review passes
- keep the canonical reconciliation key app-owned and deterministic

Design references:

- [functional-design-pr-review-followup-reconciliation.md](functional-design-pr-review-followup-reconciliation.md)
- [technical-design-pr-review-followup-reconciliation.md](technical-design-pr-review-followup-reconciliation.md)
- [functional-design-pr-review-stable-finding-identity.md](functional-design-pr-review-stable-finding-identity.md)
- [technical-design-pr-review-stable-finding-identity.md](technical-design-pr-review-stable-finding-identity.md)
- [functional-design-pr-review-structured-reconciliation.md](functional-design-pr-review-structured-reconciliation.md)
- [technical-design-pr-review-structured-reconciliation.md](technical-design-pr-review-structured-reconciliation.md)

### Phase 1: Stable Persisted Finding Identity

Goal:

- store a stable machine-facing finding identity separately from human summary
  text

Status:

- [x] extend persisted prior-review finding state with optional `identity`
- [x] derive canonical identity in application code from bounded finding fields
- [x] write identity for new persisted review passes without requiring state
      migration
- [x] load identity into prior review context when present

Done when:

- new persisted review findings carry `identity`, `summary`, and `severity`
- older persisted state without identity still loads safely
- machine matching can prefer identity without changing note wording

### Phase 2: Identity-First Reconciliation

Goal:

- make repeated-review matching prefer stable identity over title/summary
  wording

Status:

- [x] update repeated-review reconciliation to prefer exact identity matches
- [x] keep bounded legacy fallback for older history without identity
- [x] reduce title-overlap matching to legacy support instead of the primary
      path

Done when:

- repeated same-issue matches depend primarily on exact identity
- legacy state still reconciles conservatively through fallback
- wording drift no longer drives most same-issue matching behavior

### Phase 3: Structured Continuity Fields

Goal:

- prepare a later stronger continuity path where reconciliation can use bounded
  structured fields, not only title normalization

Status:

- [ ] define a minimal bounded structured finding field set such as `symbol`,
      `issue_kind`, and optional `region_hint`
- [ ] validate that the app still owns the final canonical reconciliation key
- [ ] decide whether those fields should be added now or only after stable
      identity proves useful in live testing

Done when:

- the next structured-field step is clearly scoped
- the app-owned identity rule is preserved
- the team knows whether structured fields are the next needed increment or
      still unnecessary

### Phase 4: Testing And Tightening

Goal:

- validate repeated-review continuity on real MR threads after stable identity
  is in place

Status:

- [x] add regression coverage for:
      same finding still present,
      earlier finding resolved,
      earlier finding replaced by a different new concern,
      and legacy history without identity
- [ ] collect live repeated-review examples where identity improves continuity
- [ ] watch for identity collisions or over-broad matching in live use

Done when:

- repeated-review continuity feels clearly more stable on real merge requests
- same-issue matching depends less on title wording drift
- the team has enough evidence to keep the identity shape or make one bounded
      follow-up adjustment

## Beyond V1

Post-v1 ideas and expansion tracks now live in
[future_plans.md](future_plans.md).

That includes:

- function-aware review context design
  - [functional-design-pr-review-function-aware-context.md](functional-design-pr-review-function-aware-context.md)
  - [technical-design-pr-review-function-aware-context.md](technical-design-pr-review-function-aware-context.md)
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
