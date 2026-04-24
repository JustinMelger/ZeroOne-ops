# ZeroOne Ops Roadmap

## Purpose

This roadmap is the short execution view for ZeroOne Ops.

It should answer three questions quickly:
- what is already shipped
- what still needs to happen before v1
- what is intentionally parked for post-v1

Working rule:

- after each meaningful implementation round, pause for a short cleanup review
- prefer small finishing slices over new workflow expansion during the v1 close-out

## Current Product State

Shipped baseline:

- dashboard-backed remediation with bounded structured-edit execution
- remediation reconciliation for `mr_opened` items
- merge request review with deterministic note publishing
- GitLab-backed prior-review continuity for follow-up review notes
- shared CLI, image, docs, and operator runbook
- operator-facing rebrand to `ZeroOne Ops`

Current testing focus:

- live validation of review-bot quality and reconciliation behavior
- rollout/CI hardening through repeated operator use
- keep workflow expansion constrained while these tracks absorb real usage feedback

## V1 Close-Out Plan

Goal:

- finish the remaining product-shaping work needed for a confident v1 release
  without reopening the larger architecture changes already parked for post-v1

Remaining v1 work:

1. Validate the new reconciliation flow in live use
- continue repeated merge-request testing against the current split review and overlap flow
- treat this as validation and small hardening only, not a new architecture phase
- turn remaining real misses into bounded fixes or regression coverage

2. Add remediation exclusion flow
- add the exclusion-first operator path for remediation issue classes
- keep broad default eligibility inside existing safety boundaries
- treat the dashboard as the broader work inventory while remediation intake
  decides automated pickup eligibility
- make exclusions easy to inspect later so they become a useful product
  learning surface
- use the generalized exclusion contract in
  [technical-design-remediation-exclusions.md](technical-design-remediation-exclusions.md)

Implementation phases:

Phase 1: Exclusion State Model
- [x] add a persisted repo-scoped exclusion model keyed by `source` plus `issue_key`
- [x] include a short operator reason plus basic audit fields such as updated time
      and actor when available
- [x] keep the storage shape simple and compatible with current state handling

Phase 2: Operator Edit Path
- [x] add a lightweight operator path to create and remove exclusions
- [x] treat this as remediation policy editing, even though exclusions remain
      source-aware in identity
- [x] keep the input structured and bounded rather than relying on free-form text
- [x] make the resulting exclusions easy to inspect in local and CI workflows

Phase 3: Eligibility Integration
- [x] check exclusions in remediation intake and selection, not during source sync
- [x] let explicit exclusions override broad default remediation eligibility
- [x] keep hard safety guards such as rename exclusions independent from
      operator-managed exclusions

Phase 4: Visibility And Learning Loop
- [x] surface current exclusions in a simple inspectable form for operators
- [x] keep it clear that excluded items are excluded from automation pickup,
      not erased from the broader dashboard inventory model
- [x] record enough context that repeated exclusion patterns are useful later as
      product feedback
- [x] add focused tests that prove excluded issues are skipped while normal safe
      issues still flow through

Done when:

- live reconciliation behavior stays trustworthy without needing another major
  design round
- exclusion-first remediation control exists in a form operators can use and
  inspect without maintaining a full allowlist
- the v1 workflow feels stable enough to shift effort from hardening to broader
  platform expansion

Near-term rollout prep:

- finalize the operator-facing config structure before broader remediation
  rollout
- use the compatibility-first shape in
  [technical-design-config-structure.md](technical-design-config-structure.md)
  so new repos adopt the clearer workflow/source split without forcing an
  immediate migration on existing review-only repos

## Recently Completed

Completed in the latest close-out period:

- operator-facing rebrand to `ZeroOne Ops`
- review prompt cleanup and better reasoning defaults
- GitLab-backed prior review context for follow-up continuity
- bounded overlap/reconciliation flow for repeated MR reviews
- same-file multi-edit remediation support for tightly coupled low-risk fixes
- examples, container, and docs aligned with the current product shape

## Post-V1

These are important, but intentionally not part of the v1 finish line.

### Review Pipeline Hardening

- stronger two-stage review architecture with a clearer separation between
  candidate generation and precision reconciliation
- validator-style consistency gates for contradictory review artifacts
- optional `repair_required` path before falling back to `manual_review_only`
- broader evaluator set built from real live review outcomes

### Review Continuity And Feedback

- stronger continuity benchmark coverage and live validation examples
- MR-scoped structured operator feedback for repeated reviews
- more authoritative reconciliation behavior for unresolved/new/resolved claims

### Broader Workflow Expansion

- medium-complexity remediation expansion once current low-risk boundaries stay stable
- additional remediation producers such as pipeline-failure and security-scan inputs
- dashboard readability and grouped review-history improvements where they help operators

### Service Domain Cleanup

- pure structure cleanup only
- move services into clearer domain folders without changing behavior or policy
- do this in small slices so import churn stays easy to review and rollback

Implementation phases:

Phase 1: Review Domain Move
- move review-specific services into `services/review/`
- update imports only
- keep names and behavior unchanged unless a path collision forces a minimal rename

Phase 2: Dashboard Domain Move
- move dashboard parser, renderer, service, and dashboard-specific runners/updaters
  into `services/dashboard/`
- keep the move structural only
- avoid mixing dashboard behavior cleanup into the same slice

Phase 3: Remediation Domain Move
- move remediation-specific analysis, execution, context, exclusions, and patch-flow
  services into `services/remediation/`
- keep hard workflow boundaries unchanged
- treat this as structure and imports only

Phase 4: Intake And Source Cleanup
- move source-specific intake and selector services into a clearer intake/source area
- keep source normalization boundaries explicit
- do not expand source behavior during the move

Phase 5: Shared Service Stabilization
- review what remains at the service root after the domain moves
- leave truly shared services flat or move them into a small shared area if that
  improves clarity
- stop once the leftovers are clearly shared rather than forcing uniform nesting

## Reference Docs

Use these docs when deeper detail is needed:

- [runbook.md](runbook.md)
- [technical-design-dashboard-remediation.md](technical-design-dashboard-remediation.md)
- [technical-design-pr-review.md](technical-design-pr-review.md)
- [technical-design-pr-review-overlap-reconciliation.md](technical-design-pr-review-overlap-reconciliation.md)
- [technical-design-pr-review-gitlab-prior-context.md](technical-design-pr-review-gitlab-prior-context.md)
- [technical-design-remediation-exclusions.md](technical-design-remediation-exclusions.md)
- [technical-design-config-structure.md](technical-design-config-structure.md)
- [review-bot-feedback-log.md](review-bot-feedback-log.md)
- [future_plans.md](../future_plans.md)
