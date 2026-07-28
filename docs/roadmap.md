# ZeroOne Ops Roadmap

## Purpose

This roadmap is the short execution view for ZeroOne Ops.

It should answer three questions quickly:
- what is already shipped
- what the team is focused on now
- what is intentionally parked for later

Working rule:

- prefer validation, cleanup, and sharp follow-up fixes over broad new workflow
  expansion until the live rollout feedback is well understood

## Implemented

Shipped product state:

- dashboard-backed remediation with bounded structured-edit execution
- remediation reconciliation for `mr_opened` items
- dashboard workflow board with renderer-derived buckets for:
  - `Queue Auto-fix`
  - `Needs Review`
  - `In Flight`
  - `Completed`
  - `Dismissed`
- recovery-oriented dashboard wording for failed and blocked items
- per-bucket display limits with explicit overflow summaries
- deterministic file/path-oriented workflow ordering for large repositories
- MR-scoped grouped review history with latest-pass projection
- dashboard-first operator policy with canonical severity and issue-class
  control in the dashboard
- dedicated `dashboard policy` workflow with bounded `/zeroone policy ...`
  command processing and idempotent acknowledgement notes
- optional MLflow OpenAI autologging for LLM tracing, enabled through
  environment configuration
- merge request review with deterministic note publishing
- staged review pipeline with candidate generation, precision judgment,
  continuity handling, artifact building, validator gating, same-SHA reuse,
  and review observability
- delivered review hardening slices for:
  - stable finding identity
  - published output hygiene
  - persisted review location and inline-comment metadata
  - identity-first duplicate-comment checks
  - trusted inline location validation
  - feature-flagged inline-comment rollout wiring
- GitLab-backed prior-review continuity for follow-up review notes
- operator-managed remediation exclusions
- finalized rollout-facing config structure with `review`, `remediation`, and
  `sonarqube` sections
- operator-facing rebrand to `ZeroOne Ops`
- internal package rename to `zeroone_ops`
- service and service-test domain cleanup aligned to the product structure
- review prompt cleanup and better reasoning defaults
- bounded overlap/reconciliation flow for repeated MR reviews
- same-file multi-edit remediation support for tightly coupled low-risk fixes
- rollout-facing config restructure
- dashboard schema hardening:
  - structured-block recovery truth
  - summary parsing reduction
  - projection-only renderer contract
  - historical dashboard fixtures
  - machine manifest integrity contract

## Immediate Focus

### 1. Post-Phase-5 Cleanup

- treat the GitHub control-plane architecture as implemented and ready for
  cleanup hardening rather than another broad feature branch
- tighten package boundaries around `control_plane`, provider-local GitHub
  transport, and shared orchestration seams
- remove or rename remaining false-neutral wrappers where provider-local
  behavior is still hidden behind shared names
- keep cleanup slices behavior-neutral unless they fix a real rollout issue
- prefer source/test layout cleanup that mirrors the current control-plane
  domain structure

### 2. Generic Finding Ingestion And Dogfooding

- define a provider-neutral finding ingestion boundary instead of adding
  another source-specific producer path
- wrap the current SonarQube intake behind that shared ingestion contract
- add one additional dogfooding finding source that can run on this repository
  without SonarQube availability
- use that source to live-validate the promoted GitHub work-item and review
  projection paths end-to-end
- prefer a source that gives fast local feedback over a broad discovery
  surface

### 3. Rollout And Validation

- validate the current review and remediation flows in live repositories
- treat dashboard operator policy as a testing and hardening track rather than
  a still-open implementation track
- keep collecting real review examples, remediation outcomes, and operator
  friction points
- prefer small bounded fixes over another architecture round while rollout
  signal is still forming

### 4. Results Collection

- keep extending the live feedback logs with concrete examples
- track recurring review-artifact contradictions and suppression cases
- track exclusion usage and repeated remediation skip patterns
- treat these as the evidence base for later architecture work

### 5. Review Active Testing And Hardening

- treat the staged review architecture as delivered and now in active testing
- use live review examples to drive hardening, not another architecture split
- prefer evaluator growth, observability, wording cleanup, and continuity
  stability over new review-surface expansion
- keep growing evaluator coverage and contradiction-focused review examples
- harden developer-facing wording and continuity quality from live examples
- finish rollout validation for inline comments and same-SHA reuse behavior

#### Open Review Feedback Slices

- [ ] Phase 1: Developer-Friendly Summary Note

- make the authoritative review note read like concise developer feedback
- keep the top verdict block compact and easy to scan
- keep finding explanations short, concrete, and actionable
- keep detailed wording rules in the review design docs rather than the roadmap

#### Active GitHub Review Rollout

- live-validate the GitHub summary-review path with the neutralized config
  surface
- keep dogfooding the GitHub inline-comment path for continuity and transport
  edge cases
- split GitHub review helper growth only where it improves transport,
  normalization, or thread-boundary clarity

#### Parked Operator-Feedback Research

- explicit reply invitation in the summary note stays parked until replies are
  actually consumed by the product
- bounded numbered reply intake is parked pending clearer v1 boundaries and
  authoritative-surface decisions
- continuity consumption of operator feedback is parked pending a smaller,
  safer first implementation plan
- keep the existing feedback-state and continuity research as design input, not
  as the active implementation slice

### 6. General Cleanup

- continue small codebase and docs cleanup where it improves operator or
  maintainer clarity
- keep these slices behavior-neutral unless a real rollout issue is being fixed
- current cleanup candidates:
  - finish config and state debt removal where migration compatibility is no
    longer needed
  - move remaining GitLab-specific shared services behind clearer provider-local
    boundaries
  - keep cleanup tied to clarity or real rollout issues, not speculative
    refactors

### 7. Remediation Guidance Validation

- observe whether repository guidance improves remediation quality without
  broadening selected issue scope
- verify guidance remains fix-shaping only and does not leak into review-style
  judgments
- tune prompt strength only from real remediation feedback, not speculative
  pre-adjustments

### 8. Dashboard Workflow Refinement

Next feedback-driven refinements:

- decide whether a later `Blocked` bucket earns its own place from real
  operator usage instead of adding empty buckets preemptively
- improve grouped review-history continuity summaries once unresolved/new/no
  longer present projection is trustworthy enough to surface
- consider later configurable bucket limits if operators need tuning beyond the
  current renderer-owned defaults
- continue preferring explanation and scanability improvements before adding
  mutable retry or reset commands

## Parked For Later

- broader review evaluator growth beyond the current rollout-driven hardening
- richer operator-feedback consumption for repeated reviews
- additional finding sources beyond the first post-Sonar dogfooding source
- broader dashboard readability/history improvements after current rollout
  feedback stabilizes
- any later move from CLI-backed state to an external API/database control
  plane

### GitHub Platform Status

- shipped:
  - GitHub review support, remediation publish, and control-plane Phase 5 are
    implemented
- focused on now:
  - Phase 6 cleanup, generic finding ingestion, and rollout validation
- parked:
  - any persistent overview issue remains optional and derived only
  - broader control-plane storage evolution belongs to a later API/database
    backend phase
  - after the remaining Phase 6 implementation items are complete, review the
    GitHub work-item lifecycle against the GitLab dashboard-managed runner;
    decide whether completed or dismissed GitHub work items should also use
    GitHub's native closed issue state, while keeping the shared work-item
    lifecycle authoritative

#### Phase 6a: Post-Phase-5 Cleanup

- post-Phase-5 cleanup of control-plane seams and package boundaries
- split oversized control-plane modules by concern where boundaries are now too
  broad
- align source and test layout more closely to the control-plane domain map
- clean up persistence/state naming and any compatibility leftovers that are
  now clearly debt

#### Phase 6b: Generic Finding Ingestion

Design reference:

- [design/functional/functional-design-finding-ingestion.md](design/functional/functional-design-finding-ingestion.md)
- [design/technical/technical-design-finding-ingestion.md](design/technical/technical-design-finding-ingestion.md)

##### Phase 6b1: Shared Finding Contract

- [x] define the shared normalized finding domain model
- [x] implement the bounded required finding fields:
  - `finding_id`
  - `source_id`
  - `severity`
  - `title`
  - `summary`
  - `repository_path`
  - optional location
  - structured `remediation_context`
- [x] add optional `source_metadata` behind an explicit boundary
- [x] define the shared ingestion result/interface
- [x] include bounded collection metadata for revision, artifact, and
  diagnostics in the ingestion result

##### Phase 6b2: SonarQube Behind the Shared Contract

- [x] implement shared overlap-style fallback identity for normalized findings
- [x] wrap the current SonarQube intake behind the shared ingestion contract

##### Phase 6b3: Downstream Normalization

- [x] adapt dashboard-sync downstream flow to consume normalized findings
  instead of SonarQube-local models
- [x] keep one shared default queueing and promotion policy for all normalized
  findings in this phase
- [x] defer cross-source dedupe to a later shared reconciliation stage instead
  of implementing it inside source adapters

##### Phase 6b4: First Dogfooding Source

- [x] add one bounded dogfooding source that works in this repository without
  SonarQube
- [x] implement Ruff via SARIF as the first dogfooding source

##### Phase 6b5: Remediation Normalization

- [x] close the current phase boundary where non-Sonar normalized findings can
  sync into the dashboard but still dead-end in Sonar-shaped remediation intake
- [x] normalize remediation eligibility around shared finding semantics instead
  of SonarQube-specific source checks
- [x] generalize dashboard-item selection and normalization for supported
  shared remediation categories
- [x] decide the canonical shared remediation category mapping for Ruff/SARIF
  lint findings versus existing `code_smell_fix` workflow items
- [x] keep source-local metadata out of remediation eligibility rules unless a
  field is promoted into the shared contract

##### Phase 6b6: Rollout Validation

- [x] live-test normalized ingestion for promotion
- [ ] live-test normalized ingestion for work-item lifecycle
- [ ] live-test normalized ingestion for review projection
- [ ] live-test normalized ingestion for same-SHA projection repair

#### Phase 6c: GitHub Rollout Validation

- validate the new finding ingestion path plus current GitHub
  review/remediation behavior in
  live runs
- collect operator and developer feedback from that usage
- prefer narrow rollout fixes before broadening the workflow surface again

##### Phase 6c1: GitHub Finding Sync Publication

- [x] add a real GitHub-side finding sync entrypoint instead of relying on the
  current GitLab-dashboard-wired dry-run command
- [x] publish promoted normalized findings into authoritative GitHub work-item
  issues from the sync flow
- [x] keep the GitHub sync path provider-local at the publication boundary
  while reusing shared normalized finding intake

##### Phase 6c2: GitHub Finding Lifecycle Projection

- [x] reconcile repeated finding sync runs against existing GitHub work-item
  issues instead of only creating fresh projected items
- [x] define the stale-item behavior for GitHub finding sync when a previously
  synced finding no longer appears in the current source run
- [x] validate that shared promotion decisions and GitHub work-item state stay
  aligned across repeated sync runs

##### Phase 6c3: GitHub Operator Validation

- [x] live-test GitHub finding sync with Ruff SARIF on this repository
- [ ] refine and live-validate GitHub work-item rendering so the issue reads as
  an actionable engineering task rather than a serialized control-plane record:
  - use a rendered diagnostic title and concise explanation, never unresolved
    source-message templates
  - keep status, severity, source, file/line, and diagnostic code scannable
  - collapse machine-oriented identity, provenance, and machine-state details
    without changing their authoritative representation
  - use GitHub-native wording such as `Remediation PR`
  - render remediation-PR source provenance from the originating finding (for
    example, `Ruff SARIF`) rather than the generic remediation workflow
- [ ] add a derived GitHub operational work-summary issue after lifecycle
  reconciliation is trusted:
  - render current work-item counts, active remediation PRs, recent outcomes,
    and backlog aggregates from authoritative work-item state
  - keep it read-only and non-authoritative; policy commands remain on the
    dedicated policy issue
  - cross-link the policy issue and operational summary for discovery
  - after summary behavior is live-validated, close native GitHub work-item
    issues in `completed` or `dismissed` state while retaining their
    authoritative serialized lifecycle record

##### Phase 6c4: Provider-Neutral Remediation Runner

- [x] add `zeroone-ops remediation run` as the canonical remediation command
  and retain `dashboard remediate` as a GitLab compatibility alias
- [x] introduce neutral shared remediation summary vocabulary around
  `work_item_id`, while keeping GitLab dashboard and GitHub issue references
  provider-local
- [x] add GitHub work-item intake that selects one eligible `approved` item,
  claims it as `in_progress`, and normalizes it into `RemediationExecutionTarget`;
  order by severity, creation time, and issue number while leaving `blocked`
  items untouched
- [x] route GitHub-selected work through the existing shared `ExecutionService`
  and project execution outcomes back to the authoritative GitHub work item
- [x] add the bounded GitHub work-item lifecycle manager implementation:
  - expose it through the provider-neutral operator command
    `zeroone-ops work-items sync-status`
  - mirror the established GitLab recovery rule: persist claim metadata and
    recover only unlinked `in_progress` items older than 24 hours to
    `approved`, recording the recovery for operators
  - mirror GitLab change-request convergence: keep open PRs `in_progress`;
    mark merged PRs `completed` while retaining the link; when a PR closes
    unmerged, clear the link and return the item to `approved` if the finding
    remains active upstream, mark it `completed` if it no longer does, and
    mark it `blocked` when metadata is missing, inaccessible, or inconsistent
  - move re-approval ownership out of finding sync: source sync must preserve
    remediation-owned `blocked` and intentionally terminal `dismissed` state;
    lifecycle reconciliation can re-open only a confirmed active finding after
    a closed unmerged PR, while a future explicit operator action is the only
    path back from `dismissed` to `approved`
- [ ] manually live-validate `work-items sync-status` before adding its
  scheduled GitHub workflow
- [ ] add provider-neutral remediation retry recovery for an existing unlinked
  branch: resume from the remote remediation branch after a failed change
  request publish instead of rebuilding from the default branch and failing
  with a non-fast-forward push; then create or reuse the GitLab MR or GitHub
  PR from that branch
- [x] add a manual `workflow_dispatch` GitHub remediation workflow with
  repository-wide concurrency; do not trigger remediation from issue comments
- [ ] add a scheduled GitHub remediation entrypoint after the manual live
  remediation validation succeeds
- [ ] live-test one Ruff-derived GitHub work item through remediation PR
  publication and later reconciliation

## Reference Docs

Use these docs when deeper detail is needed:

- [README.md](README.md) for the docs index
- [runbook.md](runbook.md)
- [design/technical/technical-design-dashboard-remediation.md](design/technical/technical-design-dashboard-remediation.md)
- [design/technical/technical-design-github-platform-support.md](design/technical/technical-design-github-platform-support.md)
- [design/functional/functional-design-finding-ingestion.md](design/functional/functional-design-finding-ingestion.md)
- [design/technical/technical-design-finding-ingestion.md](design/technical/technical-design-finding-ingestion.md)
- [design/technical/technical-design-pr-review.md](design/technical/technical-design-pr-review.md)
- [design/functional/functional-design-pr-review-staged-pipeline.md](design/functional/functional-design-pr-review-staged-pipeline.md)
- [design/technical/technical-design-pr-review-staged-pipeline.md](design/technical/technical-design-pr-review-staged-pipeline.md)
- [design/technical/technical-design-pr-review-overlap-reconciliation.md](design/technical/technical-design-pr-review-overlap-reconciliation.md)
- [design/technical/technical-design-pr-review-gitlab-prior-context.md](design/technical/technical-design-pr-review-gitlab-prior-context.md)
- [design/functional/functional-design-dashboard-operator-policy.md](design/functional/functional-design-dashboard-operator-policy.md)
- [design/technical/technical-design-remediation-exclusions.md](design/technical/technical-design-remediation-exclusions.md)
- [design/technical/technical-design-dashboard-operator-policy.md](design/technical/technical-design-dashboard-operator-policy.md)
- [design/technical/technical-design-config-structure.md](design/technical/technical-design-config-structure.md)
