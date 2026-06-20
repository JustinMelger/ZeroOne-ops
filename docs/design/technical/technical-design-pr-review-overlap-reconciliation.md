# PR Review Overlap Reconciliation Technical Design

## 1. Scope

This document defines a bounded technical design for splitting repeated merge
request review into two phases:

1. current-pass review
2. overlap reconciliation

It builds on:

- [functional-design-pr-review-overlap-reconciliation.md](../functional/functional-design-pr-review-overlap-reconciliation.md)
- [functional-design-pr-review-operator-feedback.md](../functional/functional-design-pr-review-operator-feedback.md)
- [technical-design-pr-review-operator-feedback.md](technical-design-pr-review-operator-feedback.md)

This design is intentionally narrow.

The first version should:

- keep the current review phase focused on current findings only
- add a second bounded overlap step that compares current findings to the
  latest prior pass on the same merge request
- keep candidate generation and final persisted state app-owned
- improve repeated-review continuity without weakening trust-first review
  behavior

It should not:

- add a broad historical reasoning engine
- let the second phase rediscover bugs from scratch
- replace app-owned identity or persisted review state
- introduce global cross-MR matching

## 2. Technical Objectives

- Reduce prompt pressure in the core review prompt by moving continuity work out
  of the current-pass review contract.
- Improve repeated-review continuity for the latest-pass comparison cases that
  now fail in live usage.
- Keep overlap matching explainable through app-owned candidate generation.
- Make overlap behavior easier to benchmark independently from current-pass bug
  discovery.
- Create a clean foundation for later provider-neutral change-request-scoped
  operator feedback across GitLab and GitHub.

## 3. Current Problem In Technical Terms

Today one flow is doing too much at once:

- the LLM reviews the current diff
- the app persists current findings
- the same rendering path tries to infer whether a finding is new, repeated, or
  no longer present

Even with stronger identity and benchmark coverage, live repeated reviews still
show a gap:

- the right current findings are often detected
- but the note still reads like a fresh review instead of a continuation

This is now more of a separation-of-responsibility problem than a raw matcher
problem.

## 4. Proposed Architecture Direction

Split the review flow into four bounded stages:

1. Build current-pass context.
2. Run current-pass review.
3. Build overlap packet from current findings plus latest prior-pass findings.
4. Run bounded overlap reconciliation and render the note from that result.

The intended ownership split is:

- app owns context building, candidate generation, identity, and persisted state
- current-pass review step owns current finding discovery only
- overlap step owns repeated-review classification only
- renderer owns note wording from structured overlap outcomes

## 5. Phase 1: Current-pass Review

### 5.1 Responsibilities

The existing review phase should keep doing only this:

- inspect the current diff and bounded repository context
- decide whether there are actionable current findings
- return the current findings with the existing bounded structured fields when
  clear

### 5.2 Explicit non-responsibilities

The current-pass review should no longer be asked to decide:

- whether a current finding is new versus repeated
- whether a prior finding is resolved
- how multiple prior findings relate to one current finding

### 5.3 Expected output

The phase can keep the existing `ReviewResult` shape, for example:

```python
class ReviewResult(BaseModel):
    classification: Literal["no_findings", "findings_present", "manual_review_only"]
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)
    confidence: float | None = None
    confidence_reason: str | None = None
```

No continuity labeling should be required here.

## 6. Phase 2: Overlap Reconciliation

### 6.1 Responsibilities

The overlap phase should receive a bounded packet and only classify:

- `still_unresolved`
- `new_in_this_pass`
- `no_longer_present`
- `overlap_ambiguous`

When bounded human feedback is available on the authoritative prior summary
comment, this stage is also the first stage allowed to consume it.

It should compare only:

- current findings from phase 1
- findings from the latest prior review pass on the same MR
- app-generated candidate overlaps
- bounded stored feedback tied to that latest prior review pass

The feedback contract consumed here should stay provider-neutral even when note
retrieval differs by platform.

### 6.2 Explicit non-responsibilities

The overlap phase should not:

- invent new code-backed findings
- search arbitrary repo context
- reason across all historical review passes at once
- own final finding identity
- treat human reactions or replies as automatic truth overrides

## 7. Proposed Data Flow

### 7.1 End-to-end flow

```text
MR + bounded code context
  -> CurrentPassReviewService
  -> ReviewResult(current findings only)
  -> OverlapPacketBuilder
  -> OverlapReconciliationService
  -> OverlapReconciliationResult
  -> ReviewNoteRenderer
  -> publish + persist latest pass
```

### 7.2 Latest prior pass only

First version should only compare against the latest prior review pass stored
for the same MR.

This keeps overlap bounded and reduces noise.

## 8. Proposed Overlap Packet

Introduce a bounded app-owned packet for phase 2.

Suggested shape:

```python
class OverlapCandidate(BaseModel):
    current_finding_index: int
    prior_finding_index: int
    reasons: list[str] = Field(default_factory=list)


class OverlapPacket(BaseModel):
    merge_request_iid: int
    current_head_sha: str
    prior_head_sha: str
    current_findings: list[ReviewFinding]
    prior_findings: list[PriorReviewFinding]
    candidates: list[OverlapCandidate] = Field(default_factory=list)
```

The exact model names can vary, but the packet should contain:

- current findings
- latest prior findings
- bounded candidate pairs
- enough revision identity to tie the comparison to one MR pass pair

## 9. Candidate Generation

Candidate generation stays app-owned and should run before the overlap step.

### 9.1 Matching signals

Candidate narrowing should continue to use bounded structured signals such as:

- canonical identity
- legacy identity
- file path
- symbol
- `issue_kind`
- optional `region_hint`
- title or summary similarity only as a fallback

### 9.2 Proposed narrowing order

The app should generate candidates conservatively in this order:

1. exact canonical identity
2. exact legacy identity
3. same file + same symbol + same issue kind
4. same file + same issue kind + compatible region hint
5. same file + bounded title overlap only when structured matching is weak or
   missing

If a current finding has no plausible candidates, it should simply be treated as
`new_in_this_pass` without asking phase 2 to guess globally.

### 9.3 Ambiguity handling

If the app produces multiple similarly strong candidates in the same file, the
packet should preserve that ambiguity rather than forcing a single winner.

This lets the second phase choose `overlap_ambiguous` instead of over-merging.

## 10. Proposed Overlap Service

Introduce a bounded overlap-focused service.

Suggested boundary:

```python
class OverlapReconciliationService:
    def reconcile(
        self,
        *,
        packet: OverlapPacket,
    ) -> OverlapReconciliationResult:
        ...
```

This service can be implemented with a second LLM step, but the packet and
result should remain app-owned models.

## 11. Prompt Contract For The Overlap Step

The overlap prompt should be much smaller than the current review prompt.

It should answer only questions like:

- does current finding A overlap with prior finding B
- does prior finding C no longer appear present in this pass
- is current finding D new in this pass
- is overlap too ambiguous to classify confidently

The prompt should not be asked to:

- discover new findings in raw code
- reassess review confidence from scratch
- infer arbitrary history beyond the latest prior pass and app-provided
  candidates

## 12. Proposed Overlap Result

Suggested bounded shape:

```python
class OverlapResolution(BaseModel):
    current_finding_index: int | None = None
    prior_finding_index: int | None = None
    outcome: Literal[
        "still_unresolved",
        "new_in_this_pass",
        "no_longer_present",
        "overlap_ambiguous",
    ]
    rationale: str | None = None


class OverlapReconciliationResult(BaseModel):
    prior_reviewed_head_sha: str
    resolutions: list[OverlapResolution] = Field(default_factory=list)
```

The app can then normalize that into the existing follow-up rendering model if
needed.

## 13. Rendering Changes

Once the overlap result exists, note rendering should rely on structured
outcomes instead of weak implicit inference.

That means the renderer can produce lines like:

- the earlier concern about `X` still appears unresolved
- the earlier concern about `Y` no longer appears present
- a new concern now appears around `Z`

This should improve repeated-review tone without asking the review prompt to do
that narrative work itself.

## 14. Persistence Direction

The app should continue to persist the latest review pass as the source of truth.

The first version does not need to persist the raw overlap packet or full raw
LLM overlap response unless that proves useful for debugging.

Reasonable first version:

- persist current findings as today
- optionally persist a normalized overlap result if later features need it
- keep canonical and legacy identity app-owned

## 15. Failure Handling

### 15.1 Current-pass review succeeds, overlap fails

If the overlap step fails or is inconclusive:

- keep the current-pass review result
- degrade continuity wording gracefully
- do not block the review note entirely

### 15.2 Ambiguous overlap

If overlap remains ambiguous after candidate narrowing:

- prefer neutral wording
- avoid strong claims that a concern is resolved or unchanged
- allow the renderer to omit stronger continuity statements when needed

This is better than overconfidently merging sibling concerns.

## 16. Benchmark And Verification Strategy

### 16.1 Benchmark suite remains the main gate

Use the continuity benchmark suite as the main regression gate, including cases
such as:

- repeated same concern across multiple passes
- mixed structured and unstructured wording drift
- sibling concern separation in the same file
- cross-file same-title non-overlap
- one-to-many ambiguous overlap
- severity drift with stable structured identity

### 16.2 New test layers

The split should be tested at three layers:

1. candidate generation tests
- verifies the app narrows candidates the way we expect

2. overlap packet / result tests
- verifies the bounded packet and normalized result handling

3. benchmark sequence tests
- verifies the repeated-review outcomes on realistic multi-pass sequences

## 17. Rollout Plan

Recommended order:

1. keep the current benchmark suite as the baseline
2. add packet-builder tests for candidate generation
3. implement the bounded overlap result model and service boundary
4. add a minimal overlap prompt and second-step execution path
5. render notes from overlap results when available
6. keep graceful fallback to the current continuity behavior during rollout

## 18. Why This Helps Operator Feedback Later

MR-scoped operator feedback depends on trustworthy same-finding continuity.

This split helps because:

- current-pass review remains about current code truth
- overlap reconciliation becomes the place where repeated-review continuity is
  decided
- later operator feedback can attach to the overlap layer instead of a mixed
  review-plus-history blur

## 19. Open Implementation Questions

The product-level direction is clear, but these implementation details should be
confirmed while building:

- whether the overlap service should return one result per current finding,
  one result per candidate pair, or a normalized final set directly
- whether raw overlap results should be persisted for debugging
- whether overlap ambiguity needs its own user-visible wording in v1 or can
  simply degrade to neutral continuity language
- whether the overlap step should be skipped entirely for `no_findings` and
  `manual_review_only` passes in the first rollout

## 20. Recommended First-Version Boundary

Keep the first implementation conservative:

- latest prior pass only
- bounded app-owned candidate packet
- bounded overlap prompt
- app-owned final state and identity
- graceful fallback when overlap is missing or ambiguous

That should be enough to improve repeated-review continuity materially without
turning the overlap step into a second general-purpose reviewer.
