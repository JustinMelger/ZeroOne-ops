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

Implementation phases:

- [x] Phase 1: Versioned Read-Only Policy Surface
- [x] add a document-level dashboard schema marker
- [x] treat missing schema markers as legacy `v0` and migrate recognized dashboards on read
- [x] render machine-owned `Automation Severity Policy` and `Excluded Issue Classes`
      sections
- [x] render a narrow grouped issue inventory for policy-relevant groups only
- [x] show read-only policy status for readability
- [x] show operator-facing status language:
      `eligible for automation`, `excluded from automation`, `blocked by severity policy`, `blocked by safety guard`

- [x] Phase 2: Dashboard Policy Action Parsing
- [x] add a compact `Operator Policy Actions` legend to the dashboard
- [x] introduce structured dashboard comment commands with a strict prefix such as
      `/zeroone policy`
- [x] add `dashboard_policy_action_service` to validate commands and reject malformed input safely
- [x] keep raw checkbox edits and direct markdown edits non-authoritative

- [x] Phase 3: Severity Policy Writes
- [x] support bounded actions for enabling and disabling `low`, `medium`, and `high`
- [x] seed dashboard severity policy once from config when no dashboard policy exists yet
- [x] after seeding, make dashboard policy authoritative for remediation pickup
- [x] re-render severity policy state from canonical dashboard policy

- [x] Phase 4: Issue-Class Exclusion Writes
- [x] support bounded actions for excluding and re-including grouped issue classes by `source + issue_key`
- [x] keep exclusions repo-wide in the first version with no operator-facing scope
- [x] re-render the `Excluded Issue Classes` section and grouped inventory from the canonical dashboard policy state
- [x] make remediation intake apply dashboard-backed issue-class policy during pickup

- [x] Phase 5: Dashboard-First Policy Authority
- [x] reduce config severity to bootstrap/fallback semantics in operator docs and workflow expectations
- [x] remove duplicate issue-class exclusion reads so dashboard policy is the only exclusion authority
- [x] keep migration and rewrite behavior explicit for future dashboard schema changes

- [ ] Phase 6: Dedicated Dashboard Policy Processing
- [x] add a separate dashboard policy-action runner/command
- [x] process strict `/zeroone policy ...` operator commands independently of remediation and reconciliation runs
- [x] keep policy mutation, validation, and dashboard re-render in the dedicated policy workflow path
- [x] preserve reconciliation as observed-state convergence only
- [x] preserve remediation as policy-consuming, not policy-mutating
- [x] rename `remediation.supported_severities` to `remediation.bootstrap_severities` and keep backward compatibility during migration

- [ ] Phase 6b: Dashboard Policy Acknowledgements
- [x] add bounded acknowledgement replies for accepted and rejected strict `/zeroone policy ...` note commands
- [x] keep dashboard policy state authoritative while reply notes remain non-authoritative workflow feedback
- [x] make acknowledgement publishing idempotent under full note replay
- [x] avoid requiring operators to separately inspect pipeline execution before knowing whether a policy command was accepted

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
