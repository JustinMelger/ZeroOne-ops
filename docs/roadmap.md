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

### 3. Review Architecture Track

- use live review examples to drive the next architecture round
- split review into clearer stages so finding generation, precision
  reconciliation, and artifact validation stop being compressed into one flow
- prefer contract-sharpening and explicit validator boundaries over broad new
  review surface expansion

Implementation phases:

- [x] Phase 1: Stage Contracts And Decision Models
  - define typed candidate, reconciled-decision, publish-artifact, and
    validator-result models
  - keep stage boundaries explicit so candidate generation does not regain
    verdict authority
  - add boundary-focused tests for model contracts and handoff semantics
- [x] Phase 2: Candidate Review Stage
  - evolve the current review analysis flow into an explicitly
    non-authoritative candidate generation stage
  - preserve candidate provenance and reconciliation outcome metadata for
    evaluation
  - keep candidate output optimized for evidence-backed recall rather than
    final review wording
- [x] Phase 3: Reconciliation / Precision Stage
  - adapt current overlap and structured-reconciliation behavior behind a new
    reconciliation-stage contract
  - make reconciliation the only stage that decides final review meaning,
    final accepted findings, and continuity outcomes
  - add review-phase checks to prevent candidate-stage or artifact-builder
    authority drift
- [x] Phase 4: Artifact Builder
  - introduce a dedicated artifact-building step that converts reconciled
    review meaning into publish-shaped output
  - keep presentation deterministic without changing review meaning
  - add tests that prove packaging changes do not alter classification or
    accepted findings
- [ ] Phase 5: Validator Gate
  - review the candidate-stage review prompt so it is optimized for
    evidence-backed recall rather than final verdict authority
  - add a strict first validator focused on contradiction-heavy high-trust
    failure classes from the live feedback log
  - validate publish-shaped artifacts only, not as a second reconciler
  - update the reconciliation / precision prompt so it reflects the new stage
    responsibilities and does not behave like a second candidate-generation
    pass
  - rename stage services and files where needed so names reflect the new
    responsibilities rather than older single-flow review terminology
  - support downgrade to `manual_review_only` when a trustworthy publish
    artifact cannot be produced
- [ ] Phase 6: Bounded Repair Path
  - add artifact-level repair for narrow contradiction classes that can be
    corrected without changing reconciled review meaning
  - record repaired publish outcomes as workflow provenance rather than a new
    operator-facing verdict class
  - downgrade instead of repairing when coherence would require changing final
    review truth
- [ ] Phase 7: Evaluation And Hardening
  - evaluate candidate-stage quality using preserved candidate metadata and
    reconciliation outcomes
  - add same-SHA stability checks and contradiction-focused evaluator coverage
  - review each implementation phase for boundary erosion and pause when stage
    ownership becomes ambiguous
  - remove transitional compatibility adapters once the staged pipeline is the
    only real review path
  - retire legacy `ReviewResult`-to-artifact adaptation from the publisher once
    artifact building is fully authoritative
  - remove compatibility-only runner and test seams that still assume the old
    compressed review flow

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
