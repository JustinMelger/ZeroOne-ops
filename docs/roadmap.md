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

## Current Product State

Shipped baseline:

- dashboard-backed remediation with bounded structured-edit execution
- remediation reconciliation for `mr_opened` items
- dashboard-first operator policy with canonical severity and issue-class
  control in the dashboard
- dedicated `dashboard policy` workflow with bounded `/zeroone policy ...`
  command processing and idempotent acknowledgement notes
- merge request review with deterministic note publishing
- staged review pipeline with candidate generation, precision judgment,
  continuity handling, artifact building, validator gating, same-SHA reuse,
  and review observability
- GitLab-backed prior-review continuity for follow-up review notes
- operator-managed remediation exclusions
- finalized rollout-facing config structure with `review`, `remediation`, and
  `sonarqube` sections
- operator-facing rebrand to `ZeroOne Ops`
- internal package rename to `zeroone_ops`
- service and service-test domain cleanup aligned to the product structure

## Immediate Focus

### 1. Rollout And Validation

- validate the current review and remediation flows in live repositories
- treat dashboard operator policy as a testing and hardening track rather than
  a still-open implementation track
- keep collecting real review examples, remediation outcomes, and operator
  friction points
- prefer small bounded fixes over another architecture round while rollout
  signal is still forming

### 2. Results Collection

- keep extending the live feedback logs with concrete examples
- track recurring review-artifact contradictions and suppression cases
- track exclusion usage and repeated remediation skip patterns
- treat these as the evidence base for later architecture work

### 3. Review Active Testing And Hardening

- treat the staged review architecture as delivered and now in active testing
- use live review examples to drive hardening, not another architecture split
- prefer evaluator growth, observability, wording cleanup, and continuity
  stability over new review-surface expansion
- keep growing evaluator coverage and contradiction-focused review examples
- compare same-SHA reruns using the new staged-review observability and reuse
  behavior
- harden developer-facing wording so published review notes stay in review
  terms and make the narrowest supported claim
- use live examples to improve continuity quality without reopening the staged
  architecture itself
- keep bounded repair parked as a later option only if live validator
  downgrade patterns prove there are narrow safe repair classes

### 4. Cleanup

- continue small codebase and docs cleanup where it improves operator or
  maintainer clarity
- keep these slices behavior-neutral unless a real rollout issue is being fixed

### 5. Dashboard Workflow Hardening

Treat the dashboard redesign as a sequence of small operator-facing slices, not
as one broad rewrite.

- [x] Phase 1: Workflow Board Split

- replace the mixed `Needs Attention` view with clearer buckets:
  - `Queue Auto-fix`
  - `Needs Review`
  - `In Flight`
  - `Completed`
- keep the first implementation renderer-derived from existing lifecycle
  states rather than introducing new persisted board-only state

- [x] Phase 2: Recovery Explanation

- improve row-level wording so failed, blocked, and manual-follow-up items
  explain their likely next step more directly
- keep `Investigate Failure` as a diagnosis label inside `Needs Review`, not a
  separate bucket
- prefer clearer explanation before adding mutable retry or reset controls

- [x] Phase 3: Dismissed Work Separation

- keep `rejected` and `ignored` out of the active operator queue
- render them later as dismissed/history-oriented outcomes instead of mixing
  them with active human follow-up work
- preserve visibility without polluting the main action board

- [x] Phase 4: Display Limits And Overflow

- add per-bucket display limits once the board split is in place
- preserve aggregate counts in the overview
- show explicit overflow summaries such as `N more items not shown`

- [x] Phase 5: Large-Repo Scanability

- add deterministic ordering and grouping for high-volume repositories
- prefer file- and path-oriented grouping before considering multi-dashboard
  monorepo splits
- use real operator feedback to decide whether a later `Blocked` bucket earns
  its own place

- [ ] Phase 6: Review History Grouping

- group repeated review passes by merge request instead of treating each pass
  as the primary dashboard row
- show the latest review state as the main visible row
- attach compact continuity summaries such as unresolved, new, or no longer
  present once that projection is trustworthy enough to present
- keep the first implementation renderer-derived rather than introducing a new
  persisted grouped-review storage model

## Recently Completed

- operator-facing rebrand to `ZeroOne Ops`
- review prompt cleanup and better reasoning defaults
- GitLab-backed prior review context for follow-up continuity
- bounded overlap/reconciliation flow for repeated MR reviews
- same-file multi-edit remediation support for tightly coupled low-risk fixes
- remediation exclusion flow
- rollout-facing config restructure
- service-domain cleanup
- service-test-domain cleanup
- internal package rename to `zeroone_ops`

## Post-V1

These are important, but intentionally not part of the immediate rollout phase.

### Review Pipeline Hardening

- broader evaluator set built from real live review outcomes
- staged-review observability and same-SHA reuse are now in place; use them to
  drive wording, continuity, and evaluator improvements from live examples
- possible later bounded artifact repair for contradiction classes proven safe
  by live validator downgrade examples

### Review Continuity And Feedback

- stronger continuity benchmark coverage and live validation examples
- MR-scoped structured operator feedback for repeated reviews
- more authoritative reconciliation behavior for unresolved/new/resolved claims

### Broader Workflow Expansion

- medium-complexity remediation expansion once current low-risk boundaries stay
  stable
- additional remediation producers such as pipeline-failure and security-scan
  inputs
- dashboard readability and grouped review-history improvements where they help
  operators

## Reference Docs

Use these docs when deeper detail is needed:

- [README.md](README.md) for the docs index
- [runbook.md](runbook.md)
- [design/technical/technical-design-dashboard-remediation.md](design/technical/technical-design-dashboard-remediation.md)
- [design/technical/technical-design-pr-review.md](design/technical/technical-design-pr-review.md)
- [design/functional/functional-design-pr-review-staged-pipeline.md](design/functional/functional-design-pr-review-staged-pipeline.md)
- [design/technical/technical-design-pr-review-staged-pipeline.md](design/technical/technical-design-pr-review-staged-pipeline.md)
- [design/technical/technical-design-pr-review-overlap-reconciliation.md](design/technical/technical-design-pr-review-overlap-reconciliation.md)
- [design/technical/technical-design-pr-review-gitlab-prior-context.md](design/technical/technical-design-pr-review-gitlab-prior-context.md)
- [design/functional/functional-design-dashboard-operator-policy.md](design/functional/functional-design-dashboard-operator-policy.md)
- [design/technical/technical-design-remediation-exclusions.md](design/technical/technical-design-remediation-exclusions.md)
- [design/technical/technical-design-dashboard-operator-policy.md](design/technical/technical-design-dashboard-operator-policy.md)
- [design/technical/technical-design-config-structure.md](design/technical/technical-design-config-structure.md)
- [review-bot-feedback-log.md](review-bot-feedback-log.md)
- [../future_plans.md](../future_plans.md)
