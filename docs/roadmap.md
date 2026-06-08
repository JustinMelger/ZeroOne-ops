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

#### Review Hardening Slices

- [x] Phase 1: Stable Finding Identity Hardening

- strengthen repeated-finding continuity across review passes
- reduce duplicates caused by wording drift before expanding publish surfaces

- [x] Phase 2: Published Output Hygiene

- tighten precision-stage prompts so published findings stay concise and
  operator-facing
- reduce overlong review text without treating it as a validator failure class

- [x] Phase 3: Persist Review Location And Comment Metadata

- extend persisted review state with the location and inline-comment metadata
  needed for continuity-safe reuse
- keep the summary note as the authoritative review-pass record

- [ ] Phase 4: Identity And Duplicate-Comment Checks

- reuse canonical finding identity for inline-comment continuity checks
- avoid posting a second near-duplicate inline comment when the same finding
  already has a trusted anchor on the latest relevant authoritative pass
- keep inline publication to one comment max per finding in the first version

- [ ] Phase 5: Trusted Location Validation

- enforce the trusted/weak/untrusted location rubric in application code
- allow inline publication only for trusted `medium` / `high` findings
- reuse anchors only when line ranges overlap or drift by at most 3 lines

- [ ] Phase 6: Config Flag And Disabled-By-Default Rollout

- add a review config flag for inline comments
- keep it off by default in repo config so implementation can ship before
  default enablement

- [ ] Phase 7: Test Deployment Validation And Live Enablement

- validate the behavior in a feature-flagged test deployment before broad
  enablement
- log trusted vs weak anchor decisions and reused vs new inline-comment
  outcomes for evaluation
- keep diagnostics compact in CI:
  - one structured decision line per finding
  - one run-level summary line
- enable per repo only after identity and location trust look good in practice

### 4. Cleanup

- continue small codebase and docs cleanup where it improves operator or
  maintainer clarity
- keep these slices behavior-neutral unless a real rollout issue is being fixed

### 5. Dashboard Workflow Refinement

The first dashboard hardening pass is now shipped.

Next feedback-driven refinements:

- decide whether a later `Blocked` bucket earns its own place from real
  operator usage instead of adding empty buckets preemptively
- improve grouped review-history continuity summaries once unresolved/new/no
  longer present projection is trustworthy enough to surface
- consider later configurable bucket limits if operators need tuning beyond the
  current renderer-owned defaults
- continue preferring explanation and scanability improvements before adding
  mutable retry or reset commands

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
- dashboard schema hardening:
  - structured-block recovery truth
  - summary parsing reduction
  - projection-only renderer contract
  - historical dashboard fixtures
  - machine manifest integrity contract

## Future Tracks

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
