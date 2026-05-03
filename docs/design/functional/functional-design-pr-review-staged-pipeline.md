# ZeroOne Ops Staged Review Pipeline Functional Design

## 1. Purpose

Define the product behavior for a staged review pipeline in ZeroOne Ops.

The current review workflow is good enough for the first live rollout, but it
still compresses too much responsibility into one step. This design describes
the next architecture track for separating:

1. candidate finding generation,
2. precision reconciliation,
3. artifact consistency validation.

This document turns the existing staged-pipeline direction from
[future_plans.md](../../../future_plans.md) into an implementation-oriented
product design, using the live failures in
[review-bot-feedback-log.md](../../review-bot-feedback-log.md) as the main
evidence base.

## 2. Goals

- separate finding discovery from final verdict authority,
- reduce cases where a valid concern is noticed internally but suppressed in
  the final classification,
- prevent contradictory review artifacts from being published as normal review
  output,
- keep the review workflow easier to reason about and test as it grows.

## 3. Non-Goals

- changing the operator-facing review surface away from merge request notes,
- replacing human review,
- widening the review workflow into code modification,
- redesigning every current continuity feature before the staged split exists.

## 4. Current Product Gap

The current review flow still asks one path to do too many things at once:

- discover possible concerns,
- judge whether they are real and in scope,
- reconcile against prior review context,
- decide final classification,
- keep the final artifact internally coherent.

The feedback log already shows the main failure modes this creates:

- `no_findings` outputs whose summary or confidence reason still describes a
  plausible regression,
- same-SHA reruns that behave too differently,
- contract or scope-overclaim language that survives final packaging even when
  the core evidence is weak,
- concerns that appear to be detected internally but do not survive the final
  classification step.

This makes the staged review pipeline the next intended architecture track
after dashboard operator-policy rollout and testing, rather than a v1 blocker
that must land before live use.

## 5. Primary User Stories

### 5.1 Better Concern Retention

As a maintainer, I want valid evidence-backed concerns to survive final review
packaging when they are warranted, so the bot does not quietly suppress a real
problem it already identified.

### 5.2 More Trustworthy Clean Passes

As a developer, I want a `no_findings` review to be internally coherent, so a
clean-pass note does not still describe a regression elsewhere in the same
artifact.

### 5.3 Clearer Stage Ownership

As a maintainer, I want candidate generation, precision decisions, and
consistency checks to have distinct responsibilities, so later improvements can
be targeted without turning one service into a catch-all review engine.

## 6. Staged Product Model

The recommended review pipeline should separate into three stages:

1. `candidate review pass`
2. `reconciliation / precision pass`
3. `validator / artifact consistency gate`

These stages do not have equal authority.

Expected authority model:

- candidate generation is exploratory and explicitly non-authoritative,
- reconciliation owns the final accepted finding set and final classification,
- artifact building owns packaging the reconciled review into publish-shaped
  form without changing review meaning,
- validation owns publish safety for contradictory or incoherent artifacts.

The stage model is intentionally asymmetric:

- candidate generation optimizes for evidence-backed recall,
- reconciliation optimizes for precision and final review meaning,
- artifact building optimizes for deterministic presentation of that meaning,
- validation optimizes for trustworthiness of the published artifact.

## 7. Candidate Review Pass

The candidate pass should:

- analyze the merge request with broader evidence-first recall,
- generate structured candidate findings,
- preserve structured location fields when the visible evidence supports them,
- allow more exploration than the final published artifact should,
- avoid acting as the final verdict authority.

It should not:

- publish the final review note,
- own unresolved/new/resolved continuity decisions,
- decide whether a contradictory final artifact is acceptable to publish.

Structured location data at this stage should stay minimal and optional:

- file path,
- line or line range when confidently supported,
- region hint or bounded evidence reference when exact line confidence is lower.

If location is uncertain, the candidate output should leave it unset rather
than guessing.

## 8. Reconciliation / Precision Pass

The reconciliation pass should:

- compare candidate findings against the actual diff,
- compare candidate findings against prior-review context when present,
- remove weak, duplicated, or already-resolved claims,
- decide the final classification and final accepted finding set.

This stage is where precision should dominate over recall.

Expected responsibilities:

- unresolved / resolved / new continuity decisions,
- scope-overclaim filtering,
- final survival of candidate findings,
- final authority on whether the review is `no_findings`,
  `findings_present`, or `manual_review_only`.

When implemented as an LLM-driven precision pass, this stage should remain
candidate-bounded rather than turning into a second general-purpose reviewer.

Expected precision-pass input shape:

- the current reviewed diff and bounded supporting context,
- the candidate finding set from the candidate stage,
- prior-review context and overlap context when available,
- clear instructions that candidate findings are the primary decision set.

Expected precision-pass output shape:

- which candidates survive,
- which candidates are dropped,
- the structured drop reason for each dropped candidate,
- an optional short note for each dropped candidate explaining the specific
  local fact that made that drop reason apply,
- the final review classification,
- bounded final reasoning for that classification,
- structured finding location data when the issue is grounded enough to support
  later inline-comment publishing.

The final classification returned by the precision pass should remain
first-class output, not something inferred later by packaging logic.

`manual_review_only` should remain an allowed precision-pass outcome when the
candidate set and visible context are still insufficient for a trustworthy
final review decision.

This should be treated as a reconciliation-owned classification outcome rather
than a vague intermediate confidence signal to be reinterpreted later by app
logic.

Expected precision-pass restrictions:

- it may accept, narrow, or drop candidate findings,
- it may use prior context to decide unresolved, resolved, or new continuity
  outcomes,
- it must not rediscover the merge request from scratch,
- it must not invent brand-new findings outside the candidate set in the first
  implementation,
- it must not silently expand scope beyond the bounded candidate evidence it
  was asked to judge.

This keeps the precision pass optimized for judgment and pruning rather than
recall.

Location data in the reconciled output should remain structured rather than
rendered:

- file path,
- line or line range when confidently known,
- evidence snippet or bounded reference when useful.

That allows later app-owned output modes such as inline comments without making
reconciliation itself responsible for transport or presentation.

## 9. Validator / Artifact Consistency Gate

The validator should inspect the final review artifact before normal publish.

Its job is not to discover new findings. Its job is to catch obviously invalid
or contradictory final combinations such as:

- `no_findings` while summary or confidence reason still describes a
  regression,
- `findings_present` while summary claims there are no actionable findings,
- rationale that undermines the final verdict,
- off-diff or over-broad impact claims that the final artifact cannot support.

The validator should act as a hard publish boundary rather than a passive
logging step.

It should begin narrowly, using contradiction classes that already appear in
the live feedback log, instead of trying to become a general second reviewer.

## 10. Fallback And Repair Behavior

When validation detects a contradiction, the system should not publish the
artifact as if it were normal and trustworthy.

Preferred direction:

1. attempt a bounded repair when that can make the artifact coherent,
2. if repair still cannot produce a trustworthy artifact, downgrade to
   `manual_review_only`,
3. avoid silently publishing a contradictory clean-pass note.

Repair should remain workflow provenance, not a separate human-facing verdict.

Repair should also remain artifact-level coherence correction rather than a
hidden second review pass.

Expected repair boundary:

- repair aligns the publish artifact to the already-reconciled review meaning,
- repair can narrow or rewrite contradictory wording when the underlying review
  decision stays the same,
- repair must not invent new findings, change final review truth, or
  reconsider the merge request from scratch.

If the contradiction cannot be fixed without changing review meaning, the
system should not treat it as repair. It should downgrade to
`manual_review_only`.

Expected product behavior:

- operators should see the final coherent published review artifact,
- internal tracking should distinguish normal publish from repaired publish,
- repair frequency should remain inspectable for later quality work without
  introducing a second visible review surface.

## 11. Evidence Inputs For The Design

This staged architecture is driven by real logged issues, not only theory.

Important design inputs include:

- same-SHA instability examples,
- verdict/reason contradiction examples,
- `no_findings` summaries or confidence reasons that still describe
  regressions,
- supported-path and runtime-overclaim examples,
- inheritance/context misses that require more disciplined final packaging.

These live examples should continue to guide the design of stage contracts and
validation rules.

The review feedback log also suggests rough ownership boundaries for failures:

- contradiction-heavy artifact failures are often validator-owned,
- unstable or weak final-survival decisions are often reconciliation-owned,
- missing or underdeveloped concern exploration can be candidate-stage owned,
- context misses can still require separate input/context improvements rather
  than stage-boundary changes alone.

## 12. Guardrails

- keep merge request notes as the primary operator surface,
- do not let the candidate pass become implicit verdict authority,
- do not let reconciliation become an unbounded second general-purpose review,
- do not let validator logic silently rewrite product truth without explicit
  fallback semantics,
- preserve deterministic publish behavior by having the publisher consume only
  validated final artifacts.

Implementation discipline matters as much as the high-level stage diagram.

Expected implementation stance:

- review each implementation phase against the intended stage boundaries,
- raise doubt explicitly when a change makes one stage smarter than its defined
  responsibility,
- prefer pausing and rethinking over quietly accepting boundary erosion for
  short-term convenience.

## 13. Rollout Direction

Recommended sequence:

1. use the current feedback log as the evidence base,
2. introduce candidate generation as an explicitly non-authoritative stage,
3. let reconciliation own final accepted findings and classification,
4. add validator-style publish gates for contradiction-heavy artifact classes,
5. grow a small evaluator set from real review outcomes to compare prompt,
   context, reconciliation, and validator changes before wider rollout.

The staged split should be introduced incrementally:

- first as a design-aligned restructuring of the current review workflow,
- then as a quality-improvement track driven by logged failures,
- and only later as a broader optimization effort once stage ownership has
  proven stable in live use.
