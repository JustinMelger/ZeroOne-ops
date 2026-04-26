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
- merge request review with deterministic note publishing
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
- keep collecting real review examples, remediation outcomes, and operator
  friction points
- prefer small bounded fixes over another architecture round while rollout
  signal is still forming

### 2. Results Collection

- keep extending the live feedback logs with concrete examples
- track recurring review-artifact contradictions and suppression cases
- track exclusion usage and repeated remediation skip patterns
- treat these as the evidence base for later architecture work

### 3. Dashboard Operator Policy

- finish the operator-filter story so dashboard policy, exclusions, and
  severity control stop being split across multiple surfaces
- design the grouped dashboard policy model before implementing new interaction
  paths
- treat review-bot improvements as lower urgency than making remediation policy
  product-shaped

### 4. Cleanup

- continue small codebase and docs cleanup where it improves operator or
  maintainer clarity
- keep these slices behavior-neutral unless a real rollout issue is being fixed

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

- medium-complexity remediation expansion once current low-risk boundaries stay
  stable
- additional remediation producers such as pipeline-failure and security-scan
  inputs
- dashboard readability and grouped review-history improvements where they help
  operators

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

- [README.md](README.md) for the docs index
- [runbook.md](runbook.md)
- [design/technical/technical-design-dashboard-remediation.md](design/technical/technical-design-dashboard-remediation.md)
- [design/technical/technical-design-pr-review.md](design/technical/technical-design-pr-review.md)
- [design/technical/technical-design-pr-review-overlap-reconciliation.md](design/technical/technical-design-pr-review-overlap-reconciliation.md)
- [design/technical/technical-design-pr-review-gitlab-prior-context.md](design/technical/technical-design-pr-review-gitlab-prior-context.md)
- [design/functional/functional-design-dashboard-operator-policy.md](design/functional/functional-design-dashboard-operator-policy.md)
- [design/technical/technical-design-remediation-exclusions.md](design/technical/technical-design-remediation-exclusions.md)
- [design/technical/technical-design-dashboard-operator-policy.md](design/technical/technical-design-dashboard-operator-policy.md)
- [design/technical/technical-design-config-structure.md](design/technical/technical-design-config-structure.md)
- [review-bot-feedback-log.md](review-bot-feedback-log.md)
- [../future_plans.md](../future_plans.md)
