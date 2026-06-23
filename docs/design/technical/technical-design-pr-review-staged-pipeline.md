# ZeroOne Ops Staged Review Pipeline Technical Design

## 1. Scope

This document defines the technical design for a staged review pipeline in
ZeroOne Ops.

It complements
[functional-design-pr-review-staged-pipeline.md](../functional/functional-design-pr-review-staged-pipeline.md),
which defines the product behavior and stage ownership.

It also turns the review-architecture direction captured in the roadmap and
Notion research/planning space into a more explicit technical contract, using
live operational feedback from Notion as the main source of concrete failure
examples.

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

### 6.1 Hardening Ownership By Stage

The next review-bot hardening work should map to stages like this:

- candidate / discovery stage
  - surface high-recall candidate concerns
  - may notice repository-guidance-backed style or readability concerns
  - attach optional location hints when visible evidence supports them
  - do not make final publish-surface decisions here
- precision / reconciliation stage
  - decide which candidates survive
  - normalize and validate identity-relevant finding inputs
  - separate actionable findings from non-actionable repository-guidance-backed
    style or readability observations
  - decide whether location evidence is strong enough to trust later for
    inline-comment publication
  - keep final finding meaning concise and bounded
- artifact builder / publisher stage
  - decide inline comment versus summary-only transport from trusted final
    location data
  - render any non-actionable style observations in a separate advisory section
  - enforce output hygiene for operator-visible text
  - keep internal analysis detail out of the final published artifact

That keeps:

- discovery broad and evidence-seeking
- precision responsible for truth and trusted finding identity
- publisher responsible for transport choice and operator-safe rendering

Repository-guidance style/readability observations should follow a separate
path from actionable findings:

- candidate stage may notice them when they are explicitly supported by
  repository guidance and clearly visible in changed code
- precision may retain them only as bounded advisory output when they are
  meaningful but intentionally non-actionable
- they must not be promoted into accepted findings unless they also meet the
  normal actionable-finding bar
- they must not become continuity-tracked findings, inline-comment candidates,
  or feedback-authoritative review surfaces

### 6.1.1 Boundary Guardrails

The implementation should keep these boundaries explicit:

- summary note authority vs inline comments
  - the summary note remains the authoritative review-pass record
  - inline comments stay subordinate transport only
- precision vs publisher
  - precision decides what is true, what survives, and whether location trust
    is sufficient
  - publisher chooses transport and final rendering without re-judging findings
- GitLab-backed continuity vs local cache
  - CI-safe continuity must be recoverable from GitLab-backed machine-managed
    review state
  - local review state may cache but must not be the only continuity source
- identity vs wording
  - canonical finding identity owns reuse and deduplication
  - note text and inline comment text must not become the real matching key
- review surface vs dashboard surface
  - merge request notes and inline comments remain the review conversation
  - dashboard mirroring stays compact and should not replay full inline comment
    content

### 6.2 Trusted Location Evidence

Location evidence should be considered trusted only when the final finding can
be anchored to a specific changed location with low ambiguity.

Recommended trust checks:

1. the finding points to a changed file in the reviewed merge request
2. the proposed line or range maps to a changed hunk or clearly adjacent
   changed context
3. the cited evidence is visibly present near that location
4. the finding is locally scoped to one clear region rather than a broad
   file-level concern
5. there is no equally plausible competing nearby anchor

Recommended trust levels:

- `trusted`
  - changed file
  - changed hunk or clearly local changed context
  - visible evidence
  - one unambiguous anchor
- `weak`
  - likely correct file
  - approximate location only
  - evidence present but not cleanly tied to one anchor
- `untrusted`
  - off-diff concern
  - file-level concern only
  - missing or conflicting anchors

Recommended transport rule:

- `trusted` -> inline comment may be published
- `weak` or `untrusted` -> summary-note rendering only
- inline comments should use a stricter brevity rule than summary-note findings
- first-version inline publication should stay limited to trusted `medium` /
  `high` findings

The application should prefer under-publishing inline comments over posting a
comment on the wrong line.

Authoritative continuity rule:

- the summary note for one reviewed SHA remains the authoritative review-pass
  record
- inline comments are subordinate finding transports attached to that same pass
- inline comments must not create their own independent continuity or feedback
  authority

That means later publish state should be able to answer:

- which authoritative summary note and reviewed SHA an inline comment belongs to
- which canonical finding identity produced that inline comment

without inferring continuity from inline comment text alone

For CI-safe continuity, that mapping should be recoverable from GitLab-backed
machine-managed review state rather than relying only on local persisted review
state.

Follow-up publish check:

- when a later review pass keeps the same canonical finding identity, the
  publish path should check whether that identity already has an inline comment
  on the latest relevant authoritative pass
- if so, avoid posting a duplicate inline comment by default
- only publish a new inline comment when the previous anchor is no longer
  suitable and the new pass has a newly trusted location
- same identity does not automatically mean the earlier inline anchor is still
  reusable; anchor reuse should be checked separately from finding continuity
- first reuse check order should be:
  - identity
  - region
  - line drift
- the first version should treat line drift as reusable only when the ranges
  overlap or move by at most 3 lines
- if a developer marked the earlier inline comment resolved, treat that as an
  advisory signal only; the next review pass still decides whether the concern
  is actually resolved
- provider-observed resolved inline-thread state should suppress automatic
  inline re-publication on the next run by default
- when the concern still appears valid, keep it in the authoritative summary
  note and prefer summary-only transport rather than reopening the subordinate
  inline thread automatically

### 6.3 Feature-Flagged Test Validation

The first rollout should use a feature-flagged test deployment rather than a
separate shadow mode.

In that test rollout, the publish path should still log:

- trusted versus weak location status
- whether a finding reused or created an inline comment
- the authoritative summary note, reviewed SHA, and canonical finding identity
  attached to that decision
- one compact run-level inline-comment summary

This keeps real-run validation available without introducing an additional
operating mode beyond the feature flag.

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

Later publish-mode decisions should also live here:

- summary-only versus inline comment transport
- compact rendering of repeated findings
- trimming or rejecting long internal-analysis text before publish

The artifact builder is not a second judge. It is a packaging boundary.

## 9. Validator Rules

The validator should begin with a narrow set of contradiction classes driven by
real logged failures.

Recommended first rules:

- reject `no_findings` artifacts that still carry accepted findings,
- reject `findings_present` artifacts that do not carry any accepted findings,
- reject `manual_review_only` artifacts that still carry accepted findings,
- reject other strict shape contradictions where the publish artifact cannot be
  interpreted coherently from its structured fields.

The validator should grow from real logged failures, not from speculative rule
sprawl.

The initial rule set should be mapped directly to known failure classes in the
feedback log so each validator rule has a concrete motivating example.

Recommended v1 boundary:

- keep strict validator rules limited to high-trust contradiction classes,
- do not let the validator reinterpret natural-language review meaning when the
  precision/reconciliation stages have already made a coherent final judgment,
- keep semantic review judgment in precision/reconciliation,
- keep structural publish safety in validator,
- keep user-facing wording and presentation guards in the publisher,
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
- emit compact structured diagnostic lines in CI logs so feature-flagged test
  rollouts can be inspected without extra tooling,
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
    inline_comment_decisions: list[InlineCommentDecision]
    final_published_finding_summaries: list[str]
    final_classification: ReviewClassification
```

Suggested inline-comment decision shape:

```python
class InlineCommentDecision(BaseModel):
    finding_identity: str
    severity: ReviewFindingSeverity
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    region_hint: str | None = None
    inline_comments_enabled: bool
    location_trust: Literal["trusted", "weak", "untrusted"]
    existing_inline_comment_found: bool
    anchor_reuse_decision: Literal["reuse", "new", "summary_only"]
    anchor_reuse_reason: str
    authoritative_note_id: int | None = None
    existing_comment_id: str | None = None
    new_comment_id: str | None = None
```

Recommended first logging shape in CI:

- one structured `InlineCommentDecision` line per evaluated finding
- one compact per-run summary with:
  - candidates considered
  - comments published
  - comments reused
  - comments skipped for untrusted location
  - comments skipped for severity threshold

Suggested usage:

- compare repeated runs on the same SHA before changing prompts or stage logic,
- identify whether a concern disappeared during candidate generation,
  grounding, or precision,
- identify whether a grounded-but-invalid concern was incorrectly promoted by
  precision,
- inspect trusted vs weak anchor decisions and reused vs new inline-comment
  outcomes during feature-flagged test rollouts.

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
