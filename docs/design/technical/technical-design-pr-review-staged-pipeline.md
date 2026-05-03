# ZeroOne Ops Staged Review Pipeline Technical Design

## 1. Scope

This document defines the technical design for a staged review pipeline in
ZeroOne Ops.

It complements
[functional-design-pr-review-staged-pipeline.md](../functional/functional-design-pr-review-staged-pipeline.md),
which defines the product behavior and stage ownership.

It also turns the review-architecture direction captured in
[future_plans.md](../../../future_plans.md) into a more explicit technical
contract, using
[review-bot-feedback-log.md](../../review-bot-feedback-log.md) as the main
source of concrete failure examples.

This technical design focuses on:

- stage boundaries,
- artifact contracts,
- runner orchestration,
- fallback semantics,
- how the new staged pipeline fits the current review architecture.

## 2. Architectural Direction

The current review runner should evolve from one compressed analysis flow into
an explicitly staged pipeline:

- `candidate_review_service`
- `review_reconciliation_service`
- `review_artifact_builder`
- `review_artifact_validator`
- existing publisher consuming only validated final artifacts

This should remain inside the MR-first review workflow. The staged split does
not introduce a second operator surface.

## 3. Why A New Staged Slice

Existing review design docs already cover:

- base review flow,
- prior-review continuity,
- overlap reconciliation,
- stable finding identity,
- operator feedback follow-up ideas.

What is still missing is a single design that explains how review should be
split into:

- high-recall candidate generation,
- precision-oriented final authority,
- explicit consistency gating before publish.

That gap matters because the feedback log now shows contradiction classes that
are not well explained by overlap or continuity design alone.

This staged design is therefore the next major architecture track after the
dashboard operator-policy work, not a retroactive rewrite of the original v1
review launch requirements.

## 4. Proposed Stage Boundaries

### 4.1 Candidate Review Service

Responsibilities:

- analyze diff and context for possible concerns,
- emit structured candidate findings,
- preserve evidence and uncertainty where useful,
- favor recall over final polish.

Suggested output shape:

- candidate findings,
- per-finding evidence summary,
- optional bounded uncertainty metadata,
- optional notes that help later deduplication or continuity matching.

Non-responsibilities:

- final classification,
- final unresolved/new/resolved continuity labeling,
- final publish safety decisions.

### 4.2 Review Reconciliation Service

Responsibilities:

- compare candidate findings against the actual diff,
- compare candidate findings against prior-review context,
- discard weak, duplicate, or already-resolved candidates,
- own the final accepted finding set,
- own the final review classification.

This service should be the final authority on review meaning, not the
candidate service.

It should also be the only stage allowed to conclude that:

- a candidate concern is strong enough to survive,
- a prior concern is unresolved, resolved, or replaced,
- the overall review is `no_findings`, `findings_present`, or
  `manual_review_only`.

### 4.3 Review Artifact Validator

Responsibilities:

- inspect the final classified artifact,
- detect contradictory combinations,
- enforce hard publish boundaries,
- trigger repair or fallback behavior when the artifact is not trustworthy.

It should not:

- rediscover new findings,
- replace reconciliation as the main precision stage.

The validator should stay deliberately narrower than the reconciler:

- reconciler decides what the review means,
- validator decides whether the resulting artifact is safe to publish as
  trustworthy output.

## 5. Recommended Artifact Flow

Suggested flow:

1. intake and build review context,
2. run `candidate_review_service`,
3. run `review_reconciliation_service`,
4. run `review_artifact_builder`,
5. run `review_artifact_validator`,
6. publish only validated final artifacts or an explicit fallback artifact.

This makes the artifact lineage visible:

- candidate artifact
- reconciled final artifact
- validated publish artifact

That lineage should remain explicit in code and tests so later changes do not
quietly collapse stage ownership back into one service.

## 6. Candidate Artifact Contract

The candidate artifact should be structured and explicitly non-authoritative.

Suggested fields:

- candidate findings,
- evidence excerpts or bounded rationale,
- uncertainty/confidence where useful,
- optional candidate-local metadata that helps later reconciliation.

Important rule:

- the candidate artifact should never be treated as the final review note.

Candidate-stage metadata should be preserved primarily for evaluation and
quality measurement, not because every internal candidate detail needs to live
forever.

Recommended preserved metadata:

- candidate identifier,
- candidate category or finding type,
- short evidence summary,
- candidate confidence or uncertainty when present,
- structured location fields when visible evidence supports them,
- reconciliation outcome,
- reconciliation drop reason code when dropped,
- final published finding identifier when the candidate survives.

This should be enough to evaluate:

- whether the candidate stage noticed concerns that later survived,
- why candidates were dropped,
- whether candidate quality is improving over time,
- whether certain candidate classes are systematically weak or unstable.

Recommended candidate location fields:

- file path,
- optional line or line range,
- optional region hint,
- optional bounded evidence reference.

These should remain nullable when the candidate stage cannot support them
confidently.

## 7. Reconciled Final Artifact Contract

The reconciliation stage should output a structured final review decision
model, not the final publish-shaped artifact.

Suggested responsibilities in that artifact:

- final classification,
- final accepted findings,
- final continuity outcomes,
- bounded reasoning fields needed for later packaging.

This reconciled output should express review meaning, but it should stop short
of final note-shaping.

Recommended boundary:

- reconciliation decides what is true and what survives,
- artifact building packages that result into publish-shaped form,
- validator checks the publish-shaped artifact for contradiction and coherence
  before normal publish.

When reconciliation becomes LLM-assisted rather than purely deterministic, the
precision-pass prompt contract should stay candidate-bounded.

Recommended prompt contract:

- inputs should include:
  - the candidate artifact,
  - the current reviewed diff and bounded code context,
  - prior-review and overlap context when available,
  - explicit instructions that the candidate set is the primary search space
    for final survival decisions
- outputs should include:
  - accepted candidate identifiers,
  - dropped candidate identifiers,
  - structured drop reasons from a fixed enum,
  - optional short notes for dropped candidates when one precise local fact
    helps explain why the enum applied,
  - final classification,
  - bounded decision rationale
- the prompt should explicitly forbid:
  - rediscovering the merge request from scratch,
  - inventing brand-new findings outside the candidate set in the first
    implementation,
  - acting like the final artifact validator or note renderer

Recommended output semantics:

- use the fixed drop-reason enum as the primary machine-readable decision,
- keep optional short notes brief and case-specific rather than free-form
  essays,
- allow the precision pass to return the final classification directly,
- keep `manual_review_only` available in the output contract when visible
  context is insufficient for a trustworthy decision.

Recommended classification ownership:

- allow the precision pass to emit `manual_review_only` directly when the
  candidate set plus visible context are insufficient for a trustworthy final
  decision,
- do not replace that with a vague intermediary confidence signal that later
  app logic must reinterpret,
- keep validator-driven downgrade to `manual_review_only` as a separate later
  publish-safety path rather than conflating it with reconciliation meaning.

That contract is what keeps an LLM-driven precision pass from collapsing back
into a second broad review pass.

This keeps review judgment separate from presentation without deferring too
much final meaning until the very end.

Suggested top-level schema:

```python
class ReconciledReviewDecision(BaseModel):
    review_classification: ReviewClassification
    decision_summary: str
    decision_rationale: str
    confidence_level: ConfidenceLevel | None
    accepted_findings: list[ReconciledFinding]
    dropped_candidates: list[DroppedCandidate]
    prior_review_context_used: bool
    same_sha_review: bool
    repair_allowed: bool
    reconciled_at: datetime
    pipeline_version: str
```

Suggested supporting models:

```python
class ReconciledFinding(BaseModel):
    finding_id: str
    title: str
    severity: ReviewFindingSeverity
    category: str
    summary: str
    evidence: list[str]
    diff_references: list[DiffReference]
    file_paths: list[str]
    why_it_matters: str
    recommended_followup: str | None
    stable_identity: StableFindingIdentity | None
    continuity_status: ContinuityStatus
    source_candidate_ids: list[str]


class DroppedCandidate(BaseModel):
    candidate_id: str
    drop_reason: DropReason
    notes: str | None
```
```

Recommended semantics:

- the reconciled decision model should capture final review meaning before note
  rendering,
- it should be rich enough for validator checks, artifact building, state, and
  evaluation,
- it should not contain final markdown or note-template formatting,
- it should preserve candidate-to-final provenance without carrying excessive
  internal candidate detail forward.
- it should preserve validated structured location data for later output modes
  such as inline comments, without making reconciliation responsible for
  transport.

Recommended rollout approach for the first LLM-assisted precision pass:

- replace the current deterministic reconciliation path directly in the test
  environment,
- avoid carrying a dual reconciliation path during the first staged rollout,
- keep validator fallback and boundary reviews tight so the replacement is
  evaluated as one coherent workflow rather than as two drifting
  implementations.

## 8. Publish-Shaped Artifact Contract

The artifact builder should transform the reconciled final review decision
model into the publish-shaped artifact inspected by validator and consumed by
publisher.

Suggested responsibilities:

- build deterministic summary wording,
- package accepted findings for the note template,
- carry through final classification and continuity outcomes unchanged,
- avoid changing review meaning during formatting.

The artifact builder is not a second judge. It is a packaging boundary.

## 9. Validator Rules

The validator should begin with a narrow set of contradiction classes driven by
real logged failures.

Recommended first rules:

- reject `no_findings` artifacts whose summary or confidence reason still
  describes an actionable regression,
- reject `findings_present` artifacts whose summary claims no actionable
  findings,
- reject artifacts whose rationale directly undermines the final
  classification,
- reject obvious off-diff or unsupported broad-impact claims when the final
  artifact overstates supported evidence.

The validator should grow from real logged failures, not from speculative rule
sprawl.

The initial rule set should be mapped directly to known failure classes in the
feedback log so each validator rule has a concrete motivating example.

Recommended v1 boundary:

- keep strict validator rules limited to high-trust contradiction classes,
- do not let the first validator become a broad wording or style police layer,
- defer softer quality checks until more live examples accumulate.

## 10. Repair And Fallback Semantics

When validator checks fail, the system should not publish the artifact as if it
were valid.

Recommended first behavior:

- allow a bounded repair pass for contradiction-heavy artifact classes,
- if repair fails or still produces an untrusted artifact, downgrade to
  `manual_review_only`,
- keep the publisher deterministic by consuming only the repaired or downgraded
  validated artifact.

This keeps contradiction handling explicit instead of silently leaking into the
normal publish path.

The first implementation can keep repair intentionally narrow. If a clean and
bounded repair path is not yet available for a contradiction class, the system
should prefer explicit downgrade over optimistic publish.

Repair must stay artifact-bounded.

Required repair contract:

- operate on the publish-shaped artifact after reconciliation,
- preserve the reconciled final review decision model,
- make the smallest bounded wording or packaging change needed to restore
  coherence,
- never introduce new findings or reclassify the review outcome.

If restoring coherence would require changing review meaning, the system should
stop repair and downgrade to `manual_review_only` instead.

Repair should be tracked as workflow provenance rather than as a separate
operator-facing verdict class.

Recommended state and runner semantics:

- publish the repaired artifact as the normal visible merge request review,
- record that the run published through repair in review state or run outcome
  metadata,
- distinguish at least:
  - `published_normal`
  - `published_repaired`
  - `published_manual_review_only`
  - `failed_before_publish`
- keep any validator rule or repair-trigger reason available for observability
  and later evaluation work.

## 11. Relationship To Existing Review Services

This new staged design should reuse existing strengths where possible.

Likely reuse points:

- current review context building remains the intake/context foundation,
- prior-review continuity services remain inputs to reconciliation,
- overlap reconciliation ideas inform reconciliation-stage continuity logic,
- stable finding identity work informs matching and deduplication,
- publisher remains downstream of validated final artifacts.

This means the staged pipeline is a restructuring of responsibility, not a full
replacement of every existing review module.

Likely mapping direction:

- `review_analysis_service` evolves toward candidate generation,
- existing overlap and structured-reconciliation work informs the
  reconciliation stage rather than living as an unrelated sidecar,
- `review_publisher` can likely be split conceptually into artifact-building
  plus final transport, even if the first implementation keeps those pieces
  close together,
- publisher stays downstream of validated artifacts,
- review dashboard mirroring remains downstream of the final published review
  result rather than becoming a separate review authority.

Recommended migration approach:

- adapt the current overlap and structured-reconciliation code in place behind
  the new reconciliation-stage contracts,
- avoid a full rewrite before the staged pipeline exists end-to-end,
- simplify or replace internal pieces incrementally once the stage boundaries
  are live and observable.

## 12. Runner Integration

The review runner should stay the composition root and orchestrate stages in
order.

Recommended evolution:

1. load config, MR data, and context,
2. run candidate generation,
3. run reconciliation,
4. build the publish-shaped artifact,
5. run validation,
6. publish the validated artifact,
7. persist state and dashboard mirror outcomes as today.

The runner should report clearly whether:

- the normal artifact published,
- a repaired artifact published,
- the run downgraded to `manual_review_only`,
- the run failed before a trustworthy artifact existed.

### 12.1 Same-SHA Default Short-Circuit

The runner should treat an already-reviewed MR revision as a short-circuit
case, not as a normal rerun case.

Recommended behavior:

1. before running candidate generation, look up whether persisted review state
   already contains an authoritative review for:
   - the same merge-request IID
   - the same head SHA
2. if such a review exists, skip candidate generation, precision, overlap,
   artifact building, and validator work
3. return an app-owned "already reviewed" outcome that references the existing
   stored review result

Recommended user-facing shape:

- keep the message short and operational, for example:
  - `No new changes after the last review.`
- optionally append the earlier classification in compact form,
  for example `Earlier classification: findings_present.`
- do not require the earlier note URL in the first implementation

Recommended source of truth:

- use persisted local review state first when it is available and trustworthy,
- use the latest authoritative machine-safe GitLab review note for the same MR
  SHA when local state is unavailable or ephemeral,
- treat GitLab machine-safe note lookup as a normal durable path in CI-style
  environments rather than only as an edge-case recovery path.

Successful-review requirement:

- apply the same-SHA short-circuit only when the earlier persisted review was a
  successful authoritative review result,
- do not short-circuit failed or incomplete earlier runs,
- allow those runs to enter the normal staged review path again.

Important non-goal:

- the "already reviewed" response must not be serialized as a new authoritative
  review artifact for continuity,
- it should not contain a normal machine-safe review-note payload that would
  make later changed-SHA continuity treat it as a fresh review pass.

This keeps repeated unchanged-SHA runs deterministic and prevents unnecessary
review drift on identical code while still preserving explicit rerun support as
possible later operator tooling.

Runner/state semantics:

- write a new run record for the same-SHA short-circuit outcome so operators
  can still see that a review workflow executed,
- do not persist that run as a new review pass for continuity purposes,
- keep future force-rerun support optional; a normal code push remains the main
  way to trigger a new authoritative review.

## 13. Observability

The staged pipeline should log enough stage-level information to make review
behavior diagnosable without exposing hidden chain-of-thought detail.

Recommended metrics or summary fields:

- candidate finding count,
- candidate finding identifiers/titles for diagnostic comparison,
- grounding accepted candidate identifiers,
- grounding dropped candidate identifiers with drop reasons,
- reconciled accepted finding count,
- reconciled accepted source candidate identifiers,
- reconciled dropped candidate identifiers with drop reasons,
- artifact-builder output shape/version when relevant,
- validator rejection count or rule type,
- repair attempted yes/no,
- final published classification,
- final published finding identifiers/titles,
- same-SHA rerun outcome category when relevant.

Stage-aware observability is important because the main quality goal is no
longer only "did review run," but also "where did weak review behavior enter
the pipeline."

Recommended observability contract:

- record a bounded per-run diagnostic artifact for internal use only,
- keep it separate from developer-facing MR notes and bounded machine-safe
  publish payloads,
- use it to compare same-SHA reruns across:
  - candidate generation drift,
  - grounding drift,
  - precision selection drift,
  - final artifact drift.

Suggested per-run diagnostic shape:

```python
class ReviewRunDiagnostics(BaseModel):
    reviewed_head_sha: str
    candidate_findings: list[DiagnosticCandidate]
    grounding_accepted_candidate_ids: list[str]
    grounding_dropped_candidates: list[DroppedCandidate]
    precision_accepted_candidate_ids: list[str]
    precision_dropped_candidates: list[DroppedCandidate]
    final_published_finding_summaries: list[str]
    final_classification: ReviewClassification
```

Suggested usage:

- compare repeated runs on the same SHA before changing prompts or stage logic,
- identify whether a concern disappeared during candidate generation,
  grounding, or precision,
- identify whether a grounded-but-invalid concern was incorrectly promoted by
  precision.

Current limitation:

- cross-run continuity memory is currently anchored only on previously accepted
  findings stored in the machine-safe review note payload,
- previously dropped candidates are not persisted across runs,
- so a concern that was deliberately dropped on one run can reappear as an
  apparently new candidate on a later rerun of the same SHA.

That limitation is acceptable for the current rollout, but it should remain
visible during same-SHA hardening because it constrains what precision can know
from prior persisted review state.

## 14. Evaluation Inputs

The feedback log should be the initial evaluator seed.

Useful first labeled buckets:

- contradiction artifacts,
- same-SHA instability,
- supported-path overclaim,
- inheritance/context misses,
- repeated-review continuity weakness.

This lets stage changes be tested against real failure classes instead of only
subjective preference.

The first evaluator set does not need to be large. A small, curated set of
logged contradictions and overclaim cases is enough to keep the staged split
grounded in real failures during initial implementation.

Candidate-stage evaluation should focus on stage quality rather than raw volume
alone. The goal is to understand how often candidate generation notices useful
concerns and what reconciliation had to filter away, not simply how many
candidates were emitted.

## 15. Open Implementation Questions

The broad stage architecture is clear, but a few technical choices can remain
open until implementation:

- whether repair is implemented immediately or after the first validator-only
  pass,
- how much candidate metadata should be persisted or kept in-memory only,

These are implementation choices inside a now-clear stage model rather than
fundamental design gaps.

## 16. Implementation Review Discipline

The main risk in this track is no longer lack of architectural direction. It is
boundary drift during implementation.

Each implementation phase should be reviewed against the intended ownership
model:

- candidate generation must stay proposal-oriented rather than regaining final
  verdict authority,
- reconciliation must remain the only stage that decides final review meaning,
- artifact building must package meaning without changing it,
- validator must enforce coherence without turning into a second reconciler,
- repair must stay bounded to artifact-level correction rather than hidden
  re-review.

When a change creates real doubt about stage ownership, the implementation
should pause and re-evaluate the boundary instead of optimizing for short-term
convenience.
