# PR Review Operator Feedback Technical Design

## 1. Scope

This document defines a bounded technical design for MR-scoped operator
feedback on numbered review findings.

It builds on:

- [functional-design-pr-review-operator-feedback.md](functional-design-pr-review-operator-feedback.md)
- [functional-design-pr-review-followup-reconciliation.md](functional-design-pr-review-followup-reconciliation.md)
- [technical-design-pr-review-followup-reconciliation.md](technical-design-pr-review-followup-reconciliation.md)
- [functional-design-pr-review-stable-finding-identity.md](functional-design-pr-review-stable-finding-identity.md)
- [functional-design-pr-review-structured-reconciliation.md](functional-design-pr-review-structured-reconciliation.md)

This design is intentionally narrow.

The first version should:

- accept only strict structured feedback commands from the latest review note
- store that feedback as MR-scoped structured state
- let later review reconciliation consume it on the same merge request

It should not:

- add global learning
- parse arbitrary free-form discussion
- move review feedback ownership into the dashboard

## 2. Technical Objectives

- Give operators a deterministic way to mark a numbered finding as `invalid` or
  `accepted`.
- Persist structured review feedback in machine-readable review state.
- Keep the feedback loop MR-scoped and tied to one reviewed revision context.
- Let later review passes acknowledge prior disagreement or acceptance without
  changing the underlying analysis step.
- Keep intake, storage, and reconciliation easy to test.

## 3. Agreed First-Version Decisions

- feedback is read from the latest review note only
- accepted commands are strict allowlisted replies such as:
  - `1 invalid`
  - `2 accepted`
- latest valid feedback wins
- feedback states are limited to:
  - `invalid`
  - `accepted`
- any MR participant may provide valid feedback in v1
- no feedback intake exists for `no_findings` or `manual_review_only` notes
- repeated disputed findings should be acknowledged as previously disputed, not
  presented as brand-new concerns

## 4. Proposed Architecture Direction

Add a small review-feedback path alongside the existing review flow:

1. review publisher posts a numbered review note,
2. note metadata for the latest review note is persisted,
3. a lightweight intake step reads replies on that latest note,
4. valid structured feedback is parsed and stored in review state,
5. later review reconciliation loads that feedback and uses it when comparing a
   new pass against prior review state.

This should remain review-owned logic.

It should not move into dashboard storage or remediation workflows.

## 5. Proposed Data Model

### 5.1 Extend persisted review state

The review state should be extended so the latest review revision can store:

- GitLab review note id
- review note URL
- review note creation or update timestamp if needed for traceability
- structured operator feedback records for that MR/revision

Suggested bounded model shape:

```python
class ReviewFindingFeedbackState(BaseModel):
    note_id: int
    reviewed_head_sha: str
    finding_number: int
    finding_identity: str | None = None
    feedback: Literal["invalid", "accepted"]
    author_username: str | None = None
    source_note_id: int
    created_at: datetime


class MergeRequestReviewState(BaseModel):
    mr_iid: int
    head_sha: str
    status: Literal["no_findings", "findings_present", "manual_review_only"]
    last_run_id: str
    findings_count: int = 0
    summary: str | None = None
    findings: list[PriorReviewFindingState] = Field(default_factory=list)
    note_id: int | None = None
    note_url: str | None = None
    operator_feedback: list[ReviewFindingFeedbackState] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)
```

The exact naming can vary, but this is the intended shape.

### 5.2 Why store both note id and reviewed SHA

`note_id` should identify the authoritative review note.
`reviewed_head_sha` should anchor the review revision.

Both are needed because:

- the note id tells us which note replies are valid intake targets
- the reviewed SHA tells reconciliation which review pass the feedback belongs
  to
- this keeps note-thread identity separate from finding identity continuity

## 6. GitLab Intake Direction

### 6.1 Authoritative note selection

For one merge request, only the latest review note should be authoritative for
feedback intake.

Recommended rule:

- load the latest persisted review state for that MR/reviewed SHA
- use its stored `note_id` as the authoritative note
- ignore replies or commands on older bot review notes

This avoids trying to merge feedback across multiple historical bot notes.

### 6.2 Intake surface

The first version should only inspect replies or discussion entries attached to
that authoritative review note.

The intake step should not scan all MR comments for fuzzy matches.

### 6.3 Strict parser

Accepted command shape should be allowlisted.

Recommended first regex shape:

```text
^\s*(\d+)\s+(invalid|accepted)\s*$
```

Rules:

- exact match only
- case-insensitive is acceptable if normalized before storage
- malformed input such as `1 invalid because...` should be ignored
- free-form comment text should not be interpreted as structured feedback

## 7. Numbering Model

Finding numbers are local to one review note.

That means:

- numbering only needs to be stable within that note
- operators target findings by number inside that note
- later passes should not rely on number continuity across notes

When feedback is stored, it should keep both:

- the local finding number for note-level traceability
- the canonical finding identity when available for later reconciliation reuse

## 8. Review Publisher Changes

`ReviewPublisher` should evolve in three small ways:

### 8.1 Numbered findings in notes

Findings in findings-present notes should be rendered with stable local numbers.

### 8.2 Operator instruction block

When the note contains numbered findings, it should include a short footer such
as:

- `1 invalid`
- `2 accepted`

And it should state:

- feedback is scoped to this merge request only
- only replies on the latest review note are used

### 8.3 Note metadata capture

When the review note is created, the publish path should persist:

- `note_id`
- `note_url`
- reviewed SHA

That metadata is needed later for feedback intake.

## 9. Review Feedback Intake Step

Introduce a small review-feedback intake step or service.

Responsibilities:

- load the authoritative latest review note for one MR
- fetch its replies from GitLab
- parse strict valid commands only
- resolve the target finding number
- optionally attach canonical finding identity from the persisted reviewed note
  state
- store structured MR-scoped feedback entries
- apply latest-valid-feedback-wins semantics

Suggested service boundary:

```python
class ReviewFeedbackIntakeService:
    def sync_latest_feedback(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
    ) -> list[ReviewFindingFeedbackState]:
        ...
```

This service should stay deterministic and small.

## 10. Reconciliation Changes

Follow-up review reconciliation should be extended to consume operator feedback
state.

Recommended behavior:

- match current findings to prior findings using existing identity-first
  reconciliation
- if the matched prior finding has latest feedback `invalid`, do not treat it
  as a brand-new concern; render it as previously disputed if it still appears
  grounded in the current pass
- if the matched prior finding has latest feedback `accepted`, reconciliation
  may acknowledge prior acceptance when useful
- if no feedback exists, keep the existing reconciliation behavior

Important boundary:

- feedback should influence presentation and continuity on that MR
- feedback should not silently mutate the raw review result or global matching
  logic

## 11. Latest-Valid-Feedback-Wins Rule

When multiple valid commands exist for the same effective target:

- same MR
- same authoritative review note
- same finding number or resolved canonical identity

The latest valid feedback should win.

Ordering should prefer:

1. explicit GitLab note creation timestamp,
2. deterministic note id ordering as a fallback if needed.

## 12. Ownership Boundaries

### 12.1 Review owns

Review should own:

- numbering findings in the note
- storing authoritative review note metadata
- intake of structured operator feedback for that note
- consuming that feedback during later MR-scoped reconciliation

### 12.2 Dashboard does not own

The dashboard may later mirror summary information, but it should not own:

- the source of truth for review feedback
- feedback parsing
- note-thread selection
- MR-scoped review continuity logic

### 12.3 Analysis does not own

The analysis step should remain unchanged.

It should not:

- parse operator feedback
- suppress findings directly from feedback state
- change prompt behavior in v1 because of stored operator disagreement

## 13. Risks

### 13.1 Wrong note targeting

Risk:

- the system may read feedback from an older bot note and apply it to the wrong
  active review context.

Mitigation:

- persist authoritative `note_id`
- only intake replies from the latest authoritative review note

### 13.2 Ambiguous finding targeting

Risk:

- number-only targeting could drift across passes.

Mitigation:

- treat numbering as local to one note only
- persist canonical finding identity when available for later reconciliation

### 13.3 Unsafe free-form parsing

Risk:

- arbitrary comment text could be misinterpreted as structured feedback.

Mitigation:

- strict allowlisted parser only
- ignore everything else

### 13.4 Scope creep into global memory

Risk:

- MR-local disagreement could become implicit global suppression.

Mitigation:

- keep feedback strictly MR-scoped in persistence and reconciliation

## 14. Recommended Implementation Order

1. extend review state to persist authoritative review note metadata,
2. number findings in findings-present review notes,
3. add the note footer describing the accepted feedback commands,
4. implement strict reply intake for the authoritative latest review note,
5. persist structured operator feedback state,
6. extend follow-up reconciliation to consume that feedback conservatively,
7. add regression coverage for invalidated and accepted finding continuity.

## 15. Verification Strategy

Add tests for:

- findings-present note includes numbering and operator instruction footer
- latest review note metadata is persisted with note id and URL
- valid replies like `1 invalid` and `2 accepted` are parsed correctly
- malformed replies are ignored
- replies on older bot notes are ignored
- latest valid feedback wins when multiple replies target the same finding
- a later review pass acknowledges a previously disputed finding on the same MR
- feedback does not affect unrelated merge requests

The most important verification outcome is that the review workflow becomes more
correctable and collaborative without introducing fuzzy parsing or global
suppression behavior.
