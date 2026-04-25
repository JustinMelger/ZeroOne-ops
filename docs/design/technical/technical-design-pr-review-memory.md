# Incremental PR Review Memory Technical Design

## 1. Scope

This document defines a conservative technical design for adding bounded prior
review memory to repeated merge request reviews.

The goal is to improve repeated-review behavior on the same merge request
without redesigning the whole review workflow.

## 2. Technical Objectives

- Reuse prior bot review results on the same MR as bounded context.
- Keep current-diff evidence as the primary review input.
- Avoid re-reporting the same unchanged findings on later review passes.
- Preserve deterministic note publishing and reviewed-SHA state tracking.

## 3. Proposed Architecture Direction

Add a small prior-review memory path inside the existing review workflow:

1. select one reviewable MR,
2. load bounded prior bot review context for that MR,
3. build the normal review context,
4. include prior review memory in the analysis prompt,
5. publish the new deterministic review note,
6. persist the new review result for future passes.

This should remain a review-owned workflow concern rather than becoming a
general dashboard-memory abstraction in the first version.

Implementation decisions for the first version:

- use persisted review state as the primary storage and retrieval path for
  prior review memory
- do not rely on GitLab note parsing as the preferred primary representation
- store bounded normalized finding summaries rather than full rendered note
  bodies
- treat repeated unresolved findings as follow-up context, not fresh findings,
  unless the new code materially changes the risk
- allow concise "no new actionable findings since the last reviewed SHA"
  language when a later pass publishes a no-findings note
- use prior review memory mainly in prompt construction, with only light
  follow-up phrasing in rendered output
- load prior review memory only from reviews authored by this bot and present
  in persisted state
- trim review history by `review.max_prior_review_passes`, not by total finding
  count
- keep repeated-finding behavior hardcoded and conservative before adding any
  separate policy config

## 4. Data Shape

Add a bounded internal model such as:

```python
class PriorReviewFinding(BaseModel):
    summary: str
    severity: str | None = None


class PriorReviewPass(BaseModel):
    reviewed_head_sha: str
    classification: Literal["findings_present", "no_findings", "manual_review_only"]
    findings_count: int
    summary: str
    findings: list[PriorReviewFinding] = Field(default_factory=list)


class PriorReviewContext(BaseModel):
    merge_request_iid: int
    passes: list[PriorReviewPass] = Field(default_factory=list)
```

The exact names can change, but the first version should stay compact and avoid
full note-body storage as prompt input.

## 5. Retrieval Strategy

### 5.1 Preferred Source

Prefer retrieving bounded prior review memory from persisted structured review
state when possible.

Candidate sources:

- local review state records keyed by MR IID and reviewed SHA,
- dashboard review metadata later, if it becomes useful for repeated review
  flows,
- GitLab notes only as a fallback reconstruction source, not the preferred
  primary representation.

### 5.2 Selection Policy

For the first version:

- only same-MR history,
- only bot-authored prior reviews,
- only the most recent bounded review passes,
- newest first or normalized into most-recent-first order.

Use `review.max_prior_review_passes` to control that history window, with a
default of `2`.

## 6. Service Responsibilities

### 6.1 Review State Service

Extend persisted review state so it can store enough structured information for
later repeated reviews, not just reviewed SHA dedupe.

The first version should persist at least:

- reviewed SHA,
- classification,
- findings count,
- short summary,
- bounded normalized findings list.

### 6.2 Prior Review Context Builder

Add a small review-owned service or helper responsible for:

- loading prior review records for the MR,
- normalizing them into bounded `PriorReviewContext`,
- returning `None` or an empty context when no prior reviews exist.

This can live inside the existing review workflow rather than as a large new
subsystem.

### 6.3 Review Context Builder

Extend the review context package to include:

- current MR metadata and diff context,
- bounded repository guidance,
- bounded prior review memory.

### 6.4 Review Analysis Service

Extend prompt construction so prior review memory is included as explicit
context.

Prompt guidance should instruct the model to:

- prefer new or unresolved findings,
- avoid repeating unchanged earlier findings as fresh discoveries,
- still rely on the current diff and code as the main evidence.

### 6.5 Review Publisher

No major redesign is needed in the first version.

Optional small improvements:

- lightweight language for unresolved earlier findings,
- lightweight language for no new findings since the last reviewed SHA.

The first version should primarily use prior review memory in prompt context,
but the rendered note should still include a small amount of incremental
follow-up framing where useful so operators can tell the bot is intentionally
continuing the same review thread.

## 7. Storage Design

The simplest first version is to extend the existing review-state JSON records.

Example shape:

```json
{
  "merge_request_reviews": {
    "123": {
      "latest_reviewed_sha": "abc123",
      "passes": [
        {
          "reviewed_head_sha": "abc123",
          "classification": "findings_present",
          "findings_count": 2,
          "summary": "One finding remains around null handling.",
          "findings": [
            { "summary": "Possible null access in request path." }
          ]
        }
      ]
    }
  }
}
```

The exact storage shape can evolve, but the first implementation should prefer:

- append-only or bounded history per MR,
- explicit reviewed SHA linkage,
- small stored summaries rather than raw rendered notes.

When loading prior review context, only the most recent
`review.max_prior_review_passes` entries should be considered.

## 8. Boundaries

- Review owns repeated-review memory.
- Dashboard remains optional supporting traceability, not the primary review
  memory engine for this slice.
- Reconciliation does not interpret or mutate repeated-review memory for normal
  review passes.
- Remediation should not consume repeated-review MR memory unless a later
  design explicitly connects the two.

## 9. Risks

### 9.1 Prompt Bloat

If prior review memory is too large, the bot may become noisier or less
focused.

Mitigation:

- strict bounded history,
- `review.max_prior_review_passes` defaulting to `2`,
- short normalized findings,
- avoid full note-body injection.

### 9.2 False Continuity

The model may over-trust prior bot findings even when the new diff changed the
situation.

Mitigation:

- explicitly instruct that current code and diff remain primary evidence,
- use prior memory as advisory context only.

### 9.3 Storage Drift

If stored prior review records become too loosely structured, later passes may
use inconsistent history.

Mitigation:

- persist compact structured fields,
- avoid relying on rendered markdown parsing where possible.

## 10. First Implementation Slice

Recommended order:

1. extend review state with bounded prior review pass storage,
2. add prior review context loading for the same MR,
3. inject bounded prior review memory into the review prompt,
4. add regression tests showing reduced repeat behavior on a later MR SHA.

## 11. Verification Strategy

Add tests for:

- no prior review history,
- one prior no-findings review,
- one prior findings-present review,
- later review on a new SHA where the same issue remains,
- later review on a new SHA where no new finding should be repeated,
- bounded history trimming.

## 12. Done Criteria

- the review bot can load bounded prior review context for the same MR,
- repeated reviews on later SHAs use that context in prompt construction,
- persisted review state stores enough structured history for reuse,
- tests cover the main repeated-review cases seen in live testing.
