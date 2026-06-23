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
- keep the remaining inline-comment rollout work scoped to:
  - feature-flagged test deployment validation
  - compact CI diagnostics for trusted vs weak anchor decisions
  - compact CI diagnostics for reused vs new inline-comment outcomes
  - per-repo enablement only after identity and location trust look good in
    practice

#### Open Review Feedback Slices

- [ ] Phase 1: Developer-Friendly Summary Note

- redesign the authoritative summary note so it reads like concise developer
  feedback instead of a repetitive generated report
- reduce repeated boilerplate and compress confidence/caution wording
- improve the top summary/verdict block for faster scanability
- use verdict vocabulary:
  - `Block`
  - `Concern`
  - `Clear`
- use risk vocabulary:
  - `High`
  - `Medium`
  - `Low`
- use confidence vocabulary:
  - `High`
  - `Medium`
  - `Low`
- keep confidence compressed to the bare label only when it is shown
- use a compact top block in this order:
  - verdict
  - risk
  - confidence
  - since last review
- show `Since last review` only when prior review history materially changes how the
  current note should be read
- keep one short summary sentence after the top block
- keep each finding explanation short and clear so a developer can immediately
  understand the issue and why it matters
- default to one short issue sentence per finding
- add a second short consequence sentence only when the impact is not already
  obvious from the issue itself, which is most common for behavioral changes
  and silent misconfiguration rather than direct runtime failures
- tighten manual-review-only fallback UX so internal validator downgrade reasons
  do not leak into the visible developer note
- keep numbered findings in the first UX slice
- do not add grouped root-cause rendering in the first UX slice
- use a smaller `Clear` note shape than findings-present notes

#### Active GitHub Review Rollout

- live-validate the GitHub summary-review path with the neutralized config
  surface
- keep dogfooding the GitHub inline-comment path for continuity and transport
  edge cases
- cleanup GitHub review client helper growth by splitting transport,
  normalization, and inline-thread helper concerns once the slice stabilizes

#### Parked Operator-Feedback Research

- explicit reply invitation in the summary note stays parked until replies are
  actually consumed by the product
- bounded numbered reply intake is parked pending clearer v1 boundaries and
  authoritative-surface decisions
- continuity consumption of operator feedback is parked pending a smaller,
  safer first implementation plan
- keep the existing feedback-state and continuity research as design input, not
  as the active next implementation slice

### 4. Cleanup

- continue small codebase and docs cleanup where it improves operator or
  maintainer clarity
- keep these slices behavior-neutral unless a real rollout issue is being fixed
- completed cleanup slice:
  - remediation path consolidation
  - removed the remaining direct Sonar remediation intake/execution path
  - reduced Sonar-shaped assumptions in the active dashboard-backed remediation
    path
- remaining cleanup candidates:
  - move `validation_commands` under the remediation config surface once that
    contract is intentionally locked
  - remove remaining flat-config compatibility and older migration-era aliases
  - move GitLab-specific merge-request services out of `services/shared` once
    provider-neutral publish/review boundaries are mature enough

### 5. Remediation Repository Guidance

The implementation slices are now shipped and in active testing.

Current rollout focus:

- observe whether repository guidance improves remediation quality without
  broadening selected issue scope
- verify guidance remains fix-shaping only and does not leak into review-style
  judgments
- tune prompt strength only from real remediation feedback, not speculative
  pre-adjustments

- add bounded repository guidance to remediation analysis and structured-edit
  prompts
- reuse the same repository guidance source/path discovery as review
- include all bounded guidance rather than trying to pre-filter relevance in the
  first version
- keep repository guidance untrusted in remediation, just like in review
- use repository guidance only to shape fix implementation choices
- do not let repository guidance expand the selected issue scope
- do not let remediation become a second review-authority surface

#### Implemented Remediation Guidance Slices

- shared guidance discovery reuse
- remediation context wiring
- prompt integration for analysis and structured-edit paths
- boundary tests proving guidance stays fix-shaping only

### 6. Dashboard Workflow Refinement

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

- GitHub platform support as a first-class product track, with review as the
  first implementation slice and broader remediation/control-plane parity to
  follow deliberately
- additional remediation producers such as pipeline-failure and security-scan
  inputs
- dashboard readability and grouped review-history improvements where they help
  operators

#### Implemented GitHub Platform Slices

- Phase 1a: provider-neutral review core
  - provider-neutral review client seam
  - neutral shared identifiers and transport errors
  - domain review vocabulary (`ChangeRequest...`, `ReviewComment`)
  - reduced direct GitLab coupling in runner, intake, and prior-context loading
- Phase 1b: review neutrality cleanup
  - removed temporary shared-core compatibility aliases and fallback fields
  - renamed remaining shared review-path modules and wording to domain language
  - migrated persisted shared review state to `ChangeRequestReviewState` with
    load-time migration for older local state
- Phase 2b: GitHub review config and documentation cleanup
  - removed the dummy top-level `gitlab` requirement for GitHub review mode
  - grouped GitHub review support under review-domain packages
  - documented the GitHub review config shape and workflow example
  - mirrored the review integration test suite to the cleaned package
    boundaries
- Phase 2: GitHub review summary support
  - support GitHub pull request intake from CI context
  - load GitHub pull request changed files and bounded review context
  - publish deterministic GitHub pull request summary comments
  - support same-SHA reuse and prior-summary continuity on GitHub
  - stop conservatively when the triggering pull request head SHA no longer
    matches the live provider head SHA
  - reduce review artifact validation to strict structural invariants so valid
    `no_findings` follow-up notes do not downgrade to `manual_review_only` from
    phrase-based heuristic matching
- Phase 3: GitHub review inline comments
  - add GitHub inline comment transport
  - suppress automatic inline re-posting on later runs for the same canonical
    finding identity when prior inline-comment metadata already exists
  - keep still-valid findings in the authoritative summary comment even when
    inline re-publication is suppressed
  - keep the summary comment authoritative
  - preserve trusted-location and identity gating before inline publication

- Provider-local GitLab review services, transport models, and GitLab CI
  environment names intentionally remain provider-specific and are not shared
  review-core debt.

#### Open GitHub Platform Slices

- [ ] Phase 4: GitHub Remediation Publish Support

- support GitHub branch and pull request publication for remediation
- preserve the current remediation execution core where it is genuinely
  provider-neutral
- avoid GitLab-specific merge-request assumptions in remediation publish flow

- [ ] Phase 5: GitHub Control Plane Design And Implementation

- design a GitHub-native dashboard or work-queue equivalent
- design the operator control and policy interaction model on GitHub
- connect remediation and review workflow status back into that control plane

- [ ] Phase 6: GitHub Platform Rollout

- dogfood GitHub review support on this repository first
- expand into broader GitHub-native workflow usage as later slices land
- validate product clarity before claiming broader platform parity

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
