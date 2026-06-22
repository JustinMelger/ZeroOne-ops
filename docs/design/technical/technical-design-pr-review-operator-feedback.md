# PR Review Operator Feedback Technical Design

## 1. Scope

This document defines a bounded technical design for change-request-scoped
developer feedback on the authoritative review summary comment.

Current status:

- this design is parked as later research
- it is not the active next implementation slice
- the immediate near-term focus is developer-facing review-note UX only

It builds on:

- [functional-design-pr-review-operator-feedback.md](../functional/functional-design-pr-review-operator-feedback.md)
- [functional-design-pr-review-followup-reconciliation.md](../functional/functional-design-pr-review-followup-reconciliation.md)
- [technical-design-pr-review-followup-reconciliation.md](technical-design-pr-review-followup-reconciliation.md)
- [functional-design-pr-review-stable-finding-identity.md](../functional/functional-design-pr-review-stable-finding-identity.md)
- [functional-design-pr-review-structured-reconciliation.md](../functional/functional-design-pr-review-structured-reconciliation.md)

This design is intentionally narrow.

The first version should:

- make the authoritative summary note explicitly invite developer response
- ingest numbered bounded replies attached to that summary note
- store that feedback as change-request-scoped structured state
- let later overlap reconciliation consume it on the same change request

It should not:

- add global learning
- parse arbitrary free-form discussion broadly
- move review feedback ownership into the dashboard
- let human response directly override first-pass code evidence

## 2. Technical Objectives

- Give developers a deterministic way to respond on the authoritative review
  summary comment.
- Persist structured review feedback in machine-readable review state.
- Keep the feedback loop change-request-scoped and tied to one reviewed
  revision context.
- Let later overlap reconciliation acknowledge prior disagreement or
  affirmation without changing the underlying analysis step.
- Keep intake, storage, and reconciliation easy to test.

## 3. Agreed First-Version Decisions

- feedback is read from the latest authoritative summary note only
- candidate generation stays unchanged
- precision reconciliation stays unchanged
- overlap reconciliation is the first stage allowed to consume stored human
  feedback
- feedback signals are intentionally small, for example:
  - `incorrect`
  - `out_of_scope`
  - `accepted`
- numbered replies are the first-class v1 input format, for example:
  - `1 incorrect`
  - `2 out-of-scope`
  - `3 accepted`
- any change-request participant may provide bounded feedback in v1
- repeated incorrect concerns should be acknowledged as previously marked
  incorrect, not presented as brand-new concerns
- repeated out-of-scope concerns should be acknowledged as previously known
  and deferred, not treated as false positives
- repeated accepted concerns should reinforce both confidence and expected
  actionability
- the same reply contract should apply across both GitLab and GitHub, with
  provider-local intake adapters behind it

## 4. Proposed Architecture Direction

Add a small review-feedback path alongside the existing review flow:

1. review publisher posts a numbered review note,
2. the note includes one short developer-response instruction block,
3. note metadata for the latest summary note is persisted,
4. a lightweight intake step reads bounded numbered replies on that note,
5. valid structured feedback is stored in review state,
6. later overlap reconciliation loads that feedback and uses it when comparing
   a new pass against prior review state.

This should remain review-owned logic.

It should not move into dashboard storage or remediation workflows.

## 5. Proposed Data Model

### 5.1 Extend persisted review state

The review state should be extended so the latest review revision can store:

- authoritative summary note id
- summary note URL
- note creation or update timestamp if needed for traceability
- structured developer feedback records for that change-request revision

Suggested bounded model shape:

```python
class ReviewFeedbackSignalState(BaseModel):
    note_id: int
    reviewed_head_sha: str
    change_request_number: int
    finding_number: int
    finding_identity: str | None = None
    signal: Literal["incorrect", "out_of_scope", "accepted"]
    source_type: Literal["reply"]
    raw_source_value: str | None = None
    author_username: str | None = None
    source_item_id: int | str | None = None
    created_at: datetime


class ChangeRequestReviewState(BaseModel):
    change_request_number: int
    head_sha: str
    status: Literal["no_findings", "findings_present", "manual_review_only"]
    last_run_id: str
    findings_count: int = 0
    summary: str | None = None
    findings: list[PriorReviewFindingState] = Field(default_factory=list)
    note_id: int | None = None
    note_url: str | None = None
    developer_feedback: list[ReviewFeedbackSignalState] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)
```

The exact naming can vary, but this is the intended shape.

### 5.2 Why store both note id and reviewed SHA

`note_id` should identify the authoritative review note.
`reviewed_head_sha` should anchor the review revision.

Both are needed because:

- the note id tells us which note replies are valid intake targets
- the reviewed SHA tells reconciliation which review pass the feedback belongs
- the finding number gives one note-local handle that can later be resolved to
  the persisted finding identity for overlap continuity
- this keeps note-thread identity separate from finding identity continuity

## 6. Provider Feedback Intake Direction

### 6.1 Authoritative note selection

For one change request, only the latest authoritative review note should be
authoritative for feedback intake.

Recommended rule:

- load the latest persisted review state for that change request / reviewed SHA
- use its stored `note_id` as the authoritative note
- ignore replies or commands on older bot review notes

This avoids trying to merge feedback across multiple historical bot notes.

This contract should be the same on both GitLab and GitHub.

Only the provider-specific note fetching and reply enumeration logic should
change across platforms.

### 6.2 Intake surface

The first version should only inspect:

- bounded replies attached to that authoritative review note

The intake step should not scan all change-request comments for fuzzy matches.

Inline comments should never become independent feedback authorities.

Even if inline comments are added later for trusted findings, structured
developer feedback should remain summary-note-only and should not be parsed from
inline comment replies.

### 6.3 Bounded classifier

Accepted signals should be allowlisted.

Recommended first reply direction:

- accept only bounded numbered reply patterns
- keep broad natural-language parsing out of the first version
- allow a small alias set to normalize common developer wording into the
  canonical stored states

Rules:

- exact allowlist only
- malformed replies should be ignored
- free-form comment text should not be interpreted as structured feedback by
  default

Recommended first regex shape:

```text
^\s*(\d+)\s+(incorrect|out-of-scope|accepted)\s*$
```

Recommended alias normalization:

- `incorrect`: `wrong`, `false`, `invalid`
- `out_of_scope`: `out-of-scope`, `out of scope`, `known`, `defer`,
  `deferred`, `not-now`, `accepted-risk`
- `accepted`: `right`, `correct`, `true`, `valid`, `accept`

## 7. Review Note Communication

The authoritative summary note should teach developers how to respond.

Recommended footer shape:

- one short line inviting numbered replies on the authoritative summary note
- explicit statement that the feedback is scoped to this change request only

This is intentionally communication design as well as data design.

## 8. Review Publisher Changes

`ReviewPublisher` should evolve in three small ways:

### 8.1 Developer-friendly summary note

The authoritative summary note should feel closer to concise engineer feedback
than a serialized machine report.

The first humanization pass should stay presentation-only.

It should not:

- change candidate generation behavior
- change precision judgment behavior
- weaken evidence requirements
- add theatrical reviewer personas

It should:

- open with a short high-signal summary
- reduce repeated boilerplate where the same structure adds no value
- keep findings direct and specific
- invite developer response explicitly on the summary comment
- read like concise developer feedback rather than a repetitive generated report

UX rules for the first humanization pass:

- prefer concise reviewer language over serialized report formatting
- avoid repeating the same section labels and phrasing on every finding when
  the content can stay clear without them
- vary sentence structure lightly by concern type while keeping the same
  underlying meaning
- optimize for fast scanability by developers reading PR feedback in context
- keep confidence and caution visible, but compressed
- keep out-of-scope concerns clearly distinguished from accepted and
  actionable concerns
- keep each finding explanation short enough to scan quickly, but clear enough
  that a developer immediately understands what is wrong and why it matters
- do not trade clarity for compression; when compressed wording becomes
  ambiguous, prefer one extra sentence over a cryptic summary

Recommended first note structure:

1. `Verdict`
2. `Risk`
3. `Confidence`
4. `Continuity`
5. short summary sentence
6. compact findings section
7. short feedback footer when that later feature is actually enabled

Recommended first top block shape:

```text
Verdict: Block
Risk: High
Confidence: High
Continuity: 1 repeated, 2 new
```

Recommended first verdict vocabulary:

- `Block`
  - actionable findings are serious enough that the change request should not
    merge as-is
- `Concern`
  - actionable findings exist, but they do not clearly justify a hard block
- `Clear`
  - no actionable concerns were found

Recommended first risk vocabulary:

- `High`
- `Medium`
- `Low`

Recommended first confidence vocabulary:

- `High`
- `Medium`
- `Low`

Confidence should stay compressed in the human-facing note:

- default to the bare label only
- do not add a qualifier by default
- only revisit qualifiers later if live usage shows a real interpretation gap

Verdict and risk should stay distinct:

- verdict expresses review stance or merge posture
- risk expresses likely impact or severity

Expected interaction:

- `Concern` should be the default when actionable findings exist but a hard
  block would overstate the situation
- `Block` should stay meaningful and should not be used for every valid
  finding

Continuity visibility rule:

- show `Continuity` only when prior review history materially changes how the
  current note should be read
- omit `Continuity` entirely when there is no meaningful prior-review context
  to summarize

Examples where continuity is informative:

- `Continuity: 1 repeated, 2 new`
- `Continuity: 2 repeated`
- `Continuity: 1 repeated, 1 resolved`

Examples where continuity should usually be omitted:

- first review on the change request
- no prior review state exists
- all concerns are new and prior history adds no useful interpretation

Recommended first summary sentence shape:

- one short sentence describing the main developer action or concern
- avoid repeating full finding detail in the summary block
- keep the short summary sentence even when the top block is already present

Recommended first finding shape:

- file or path context
- one short statement of the issue
- one short consequence sentence only when the issue sentence does not already
  make the impact clear
- one short `Suggested fix:` line when the structured follow-up text is present

Consequence-sentence rule:

- default to one short issue sentence
- add a second short consequence sentence only when the impact is not already
  obvious from the issue itself
- this is most often needed for:
  - behavioral regressions
  - silent fallback or silent misconfiguration
  - subtle logic changes where the consequence is not obvious from the defect
    statement alone
- this is usually not needed for:
  - deterministic runtime failures
  - direct exception paths
  - obvious hard failures where the issue sentence already carries the
    consequence

Example:

```text
1. `src/vehicle_lookup_service.py`
   Unchecked access to `vehicle.types[0]` can raise `IndexError` on valid
   empty-list input.
```

Suggested-fix rule:

- render `Suggested fix:` when the structured `suggested_follow_up` text is
  present
- keep it to one short line
- do not restore separate `Evidence`, `Impact`, or `Follow-up` blocks

Recommended follow-up summary transition matrix:

- `now` signals that the current pass changed state relative to the prior pass
- `still` signals that the same review posture persists across passes
- avoid `again`; it reads more procedural and less reviewer-like
- `Needs review` notes should keep a short visible reason line after the summary

Current `Clear`:

- first pass:
  - `I don't see any actionable concerns in these changes.`
  - allow one extra short detail sentence when the `no_findings` summary is
    informative
- follow-up from `Concern`:
  - `I took another look, and I don't see any actionable concerns in these changes now.`
- follow-up from `Needs review`:
  - `I took another look, and I don't see any actionable concerns in these changes now.`
  - allow one extra short detail sentence when the `no_findings` summary is
    informative

Clear-detail rule:

- informative `Clear` summaries may render one extra short trust-building
  sentence
- generic summaries such as `No actionable findings in this review pass` should
  stay hidden from the visible note body
- continuity-style resolution wording such as `The earlier concern is no longer
  present...` must only be shown when the latest prior pass was
  `findings_present` or `manual_review_only`
- first-pass clear notes may still show one short informative detail sentence
  when it describes what the bot concluded about the diff itself rather than
  prior-review continuity

Current `Concern`:

- first pass:
  - `I noticed one actionable concern in these changes.`
  - `I noticed {n} actionable concerns in these changes.`
- follow-up from `Clear`:
  - `I took another look, and I noticed one actionable concern in these changes now.`
  - `I took another look, and I noticed {n} actionable concerns in these changes now.`
- follow-up from `Concern`:
  - `I took another look, and I still notice one actionable concern in these changes.`
  - `I took another look, and I still notice {n} actionable concerns in these changes.`
- follow-up from `Needs review`:
  - `I took another look, and I now notice one actionable concern in these changes.`
  - `I took another look, and I now notice {n} actionable concerns in these changes.`

Current `Block`:

- first pass:
  - `I'd block this because of one actionable concern.`
  - `I'd block this because of {n} actionable concerns.`
- follow-up from `Clear`:
  - `I took another look, and I'd block this now because of one actionable concern.`
  - `I took another look, and I'd block this now because of {n} actionable concerns.`
- follow-up from `Concern`:
  - `I took another look, and I'd block this now because of one actionable concern.`
  - `I took another look, and I'd block this now because of {n} actionable concerns.`
- follow-up from `Block`:
  - `I took another look, and I'd still block this because of one actionable concern.`
  - `I took another look, and I'd still block this because of {n} actionable concerns.`
- follow-up from `Needs review`:
  - `I took another look, and I'd now block this because of one actionable concern.`
  - `I took another look, and I'd now block this because of {n} actionable concerns.`

Current `Needs review`:

- first pass:
  - `I couldn't review these changes confidently enough to call them clear.`
- follow-up from `Clear`:
  - `I took another look, but I couldn't review these changes confidently enough to call them clear this time.`
- follow-up from `Concern`:
  - `I took another look, but I couldn't review these changes confidently enough to confirm the earlier concern this time.`
- follow-up from `Block`:
  - `I took another look, but I couldn't review these changes confidently enough to confirm the earlier blocking concern this time.`
- follow-up from `Needs review`:
  - `I took another look, but I still couldn't review these changes confidently enough to call them clear.`

Where repeated findings share one clear underlying cause, the renderer may
later group them conservatively, but only when the shared cause is explicit in
the structured result.

Grouping rule for the first UX slice:

- do not introduce grouped root-cause rendering yet
- keep numbered findings as the first implementation shape

No-findings rule for the first UX slice:

- `Clear` notes should use a smaller variant than findings-present notes
- keep `Verdict` and `Confidence`
- omit `Continuity` unless prior review history materially changes
  interpretation
- keep one short summary sentence
- allow one extra short detail sentence when it increases trust and does not
  overstate prior-review continuity

### 8.2 Developer-response footer

The summary note should include a short feedback instruction block.

Recommended first wording direction:

- reply here with `1 incorrect`, `2 out-of-scope`, or `3 accepted`
- feedback is scoped to this change request only
- later follow-up reviews may use that feedback as continuity context

This block should be short and easy to scan. It should not read like a policy
manual.

### 8.3 Note metadata capture

When the review note is created, the publish path should persist:

- `note_id`
- `note_url`
- reviewed SHA

That metadata is needed later for feedback intake.

### 8.4 No judgment change here

Publisher changes must not alter candidate or precision behavior.

The summary layout and footer only improve communication and teach developers
that responses are welcome.

## 9. Review Feedback Intake Step

Introduce a small review-feedback intake step or service.

Responsibilities:

- load the authoritative latest review note for one change request
- fetch bounded replies from the active provider
- parse only allowlisted numbered reply signals
- persist the note-local finding number directly
- optionally attach canonical finding identity later when overlap reasoning can
  tie the reply target to a repeated concern
- store structured change-request-scoped feedback entries
- apply latest-valid-feedback-wins semantics

Suggested service boundary:

```python
class ReviewFeedbackIntakeService:
    def sync_latest_feedback(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> list[ReviewFeedbackSignalState]:
        ...
```

This service should stay deterministic and small.

## 10. Reconciliation Changes

Follow-up review reconciliation should be extended to consume operator feedback
state.

Recommended behavior:

- match current findings to prior findings using existing identity-first
  reconciliation
- if the matched prior finding has latest feedback `incorrect`, do not treat it
  as a brand-new concern; render it as previously marked incorrect if it still
  appears grounded in the current pass
- if the matched prior finding has latest feedback `out_of_scope`,
  reconciliation may acknowledge that the concern was previously known and
  deferred or handled elsewhere when useful
- if the matched prior finding has latest feedback `accepted`,
  reconciliation may keep confidence and actionability high and acknowledge
  that the concern was previously accepted for remediation or follow-up
- if no feedback exists, keep the existing reconciliation behavior

Important boundary:

- feedback should influence presentation and continuity on that change request
- feedback should not silently mutate the raw review result or global matching
  logic

Signal-specific continuity intent:

- `incorrect` affects trust and may suppress or heavily down-rank similar future
  findings when independent evidence is weak
- `out_of_scope` affects presentation and actionability, not base detection
  confidence
- `accepted` reinforces both confidence and actionability

## 11. Latest-Valid-Feedback-Wins Rule

When multiple valid commands exist for the same effective target:

- same change request
- same authoritative review note
- same finding number or resolved canonical identity

The latest valid feedback should win.

Ordering should prefer:

1. explicit provider note creation timestamp,
2. deterministic note id ordering as a fallback if needed.

## 12. Ownership Boundaries

### 12.1 Review owns

Review should own:

- numbering findings in the note
- storing authoritative review note metadata
- intake of structured operator feedback for that note
- consuming that feedback during later change-request-scoped reconciliation

### 12.2 Dashboard does not own

The dashboard may later mirror summary information, but it should not own:

- the source of truth for review feedback
- feedback parsing
- note-thread selection
- change-request-scoped review continuity logic

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

- change-request-local disagreement could become implicit global suppression.

Mitigation:

- keep feedback strictly change-request-scoped in persistence and
  reconciliation
- keep the reply contract provider-neutral even when the implementation lands
  incrementally by provider

## 14. Recommended Implementation Order

1. extend review state to persist authoritative review note metadata,
2. number findings in findings-present review notes,
3. add the note footer describing the bounded feedback reply syntax,
4. implement strict numbered-reply intake for the authoritative latest review
   note,
5. persist structured operator feedback state,
6. extend follow-up reconciliation to consume that feedback conservatively,
7. add regression coverage for incorrect, out-of-scope, and accepted finding
   continuity on both GitLab and GitHub.

## 15. Verification Strategy

Add tests for:

- findings-present note includes numbering and operator instruction footer
- latest review note metadata is persisted with note id and URL
- valid replies like `1 incorrect`, `2 out-of-scope`, and `3 accepted` are
  parsed correctly
- accepted aliases normalize to the canonical stored states correctly
- malformed replies are ignored
- replies on older bot notes are ignored
- latest valid feedback wins when multiple replies target the same finding
- a later review pass acknowledges a previously incorrect finding on the same
  change request
- a later review pass acknowledges a previously out-of-scope finding on the
  same change request
- a later review pass acknowledges a previously accepted finding on the same
  change request
- feedback does not affect unrelated change requests
- the same bounded reply contract works on both GitLab and GitHub

The most important verification outcome is that the review workflow becomes more
correctable and collaborative without introducing fuzzy parsing or global
suppression behavior.
