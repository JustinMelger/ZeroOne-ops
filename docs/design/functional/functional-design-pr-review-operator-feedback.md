# Functional Design: PR Review Operator Feedback

## Purpose

Add a lightweight way for operators or developers to respond on the
authoritative review summary comment and let later follow-up reviews take that
feedback into account.

Current status:

- this design is parked as later research
- it is not the active next implementation slice
- the immediate near-term focus is developer-facing review-note UX only

The goal is to close the missing feedback loop in the review workflow without
changing candidate generation or precision judgment behavior and without
introducing global memory.

This design should make repeated reviews on the same change request feel more
collaborative and less stubborn when a human has already corrected the bot.

## Problem

The current review flow can:

- generate review findings
- persist prior review state
- reconcile repeated passes on the same change request

But it still cannot absorb a simple human response such as:

- this concern is incorrect
- this concern is real, but out of scope for this change request
- this issue is known and will be handled elsewhere

That leaves the workflow with an important gap:

- the bot can speak
- the human can disagree
- but the system does not yet store or apply that disagreement in a structured
  way on later passes of the same change request

## Goal

Introduce bounded change-request-scoped review feedback so that:

- the summary review note explicitly tells developers how to respond
- bounded feedback from that authoritative summary comment is stored as
  structured state
- later review passes on the same change request can acknowledge prior
  incorrect, out-of-scope, or accepted handling when repeated concerns appear
  again
- the feedback loop improves trust without changing core review judgment logic

## Non-Goals

- no global suppression across change requests or repositories
- no broad natural-language interpretation of arbitrary free-form comments in v1
- no dashboard-owned source of truth for review feedback
- no rewriting of historical review notes
- no direct modification of the underlying review analysis result
- no first-pass bug suppression based only on reactions or replies

## Boundaries

### 1. Merge-request scoped only

Feedback belongs to one change request.

That means:

- feedback should only affect later review passes on that same change request
- feedback should not be treated as repository-wide truth
- one developer marking a finding incorrect on one change request must not
  teach
  the bot to suppress that finding everywhere else

### 2. Authoritative summary comment only in v1

The first version should only accept feedback attached to the authoritative
summary review comment.

That means:

- numbered bounded replies on the summary review comment are the primary
  feedback input
- reactions may be supported later as a smaller secondary signal
- inline comments are not independent feedback authorities
- arbitrary earlier bot comments do not become feedback sources

### 3. Review reconciliation owns the feature

The source of truth for this feature should live with review continuity and
review state, not with the dashboard.

The dashboard may later mirror a high-level summary such as:

- feedback received
- number of incorrect, out-of-scope, or accepted findings

But it should not own the authoritative feedback record.

### 4. Candidate and precision stages stay unchanged

Candidate generation and precision judgment should stay unchanged.

That means:

- current-pass bug discovery still depends on code evidence only
- precision filtering still decides what is actionable in this pass
- human feedback only enters later when repeated-review continuity is evaluated

## Desired Outcome

Repeated reviews on the same change request should feel more like:

- this concern was reported earlier and still appears unresolved
- this concern was reported earlier but no longer appears present
- this concern was previously marked incorrect on this change request
- this concern was previously treated as out of scope for this change request
- this concern was previously accepted as actionable on this change request
- this is a new concern in this pass

rather than:

- the bot re-reporting the same rejected finding as if it were brand new

## Functional Direction

### 1. Structured feedback intake

Developers should be able to reply directly on the authoritative review summary
comment using a bounded numbered format.

The workflow should:

- detect the change request and reviewed revision
- read feedback only from the summary comment thread
- classify bounded feedback into a small continuity-facing signal set
- store the result as structured review feedback

The intake path should stay bounded in v1.

That means:

- replies should be interpreted conservatively and only when they match a
  bounded numbered feedback pattern
- broad free-form discussion should not become a general reasoning substrate
- the bot should not attempt to infer code truth from social feedback alone

### 2. Minimal feedback vocabulary

The first feedback vocabulary should stay very small.

Recommended first values:

- `incorrect`
- `out_of_scope`
- `accepted`

Why this set:

- `incorrect` captures that the finding itself should not be trusted as a valid
  concern
- `out_of_scope` captures that the finding is real, but not expected to be
  fixed in this change request
- `accepted` captures that the finding is real and should be treated as
  actionable for remediation or follow-up
- keeping the vocabulary smaller in v1 reduces ambiguity and parser surface

Recommended first reply shapes:

- `1 incorrect`
- `2 out-of-scope`
- `3 accepted`

Accepted aliases may be broader than the canonical syntax. For example:

- `incorrect`: `wrong`, `false`, `invalid`
- `out_of_scope`: `out-of-scope`, `out of scope`, `known`, `defer`,
  `deferred`, `not-now`, `accepted-risk`
- `accepted`: `right`, `correct`, `true`, `valid`, `accept`

The canonical stored states should still remain:

- `incorrect`
- `out_of_scope`
- `accepted`

The leading number is local to the authoritative summary note only. It gives
the system a deterministic way to connect feedback to the right repeated
concern later through overlap continuity.

This feedback contract should be shared across both GitLab and GitHub.

Only the provider-specific retrieval and publication surfaces may differ. The
developer-facing reply format and continuity meaning should stay the same
across both platforms.

### 2a. Operator prompting in the review note

The review note itself should teach developers that they can respond on the
summary comment.

The first version should include one short instruction block near the end of
the note, for example:

- reply here with `1 incorrect`, `2 out-of-scope`, or `3 accepted`
- this feedback is scoped to this change request only
- future follow-up reviews may use that feedback as continuity context

This keeps discovery close to the workflow and avoids requiring developers to
learn the format from separate documentation first.

### 3. Structured persisted state

Feedback should be stored in a structured machine-friendly form linked to:

- change request number
- reviewed head SHA or review revision key
- authoritative summary note id
- finding number within that authoritative note
- feedback signal type
- optional linked finding identity when the feedback can be tied to one repeated
  concern later
- author metadata
- timestamp

In v1, any change-request participant may provide valid bounded feedback.

This should make later reconciliation deterministic.

### 4. Follow-up reconciliation behavior

Later review passes on the same change request should use stored feedback
conservatively.

Examples:

- if the same concern returns and earlier feedback marked it `incorrect`, the
  bot should not present it as a brand-new concern; it should acknowledge that
  the concern was previously marked incorrect on this change request
- if the same concern returns and earlier feedback marked it `out_of_scope`,
  the bot should acknowledge that the concern was previously accepted as real
  but deferred or out of scope for that earlier change request
- if the same concern returns and earlier feedback marked it `accepted`, the
  bot may keep confidence and actionability high and acknowledge that the
  concern was previously accepted for remediation or follow-up
- when multiple valid feedback signals exist, the latest bounded signal should
  win for continuity framing

The continuity intent should differ by signal:

- `incorrect` should reduce trust in similar future findings and may suppress or
  heavily down-rank repeated variants when evidence is otherwise weak
- `out_of_scope` should not suppress the concern, but should change future
  presentation toward known/deferred wording
- `accepted` should reinforce both confidence and actionability for repeated
  concerns

The numbered reply should act as the first stable handle:

- it is stable within one authoritative summary note
- it can be mapped to the persisted finding identity for that note when one
  exists
- overlap continuity can then use the resolved finding identity rather than
  relying on the number across notes

The exact note wording can stay flexible, but the behavior should be grounded in
structured state.

### 5. Separation from analysis

This feature should not alter the underlying review model or its raw output.

Instead:

- analysis still produces a review result
- overlap reconciliation later compares that result to prior review state plus
  bounded human feedback
- note rendering then decides how to present still-open, resolved, incorrect,
  out-of-scope, accepted, or new concerns

This keeps the feedback loop additive and bounded.

## Source Of Truth

The source of truth should be structured persisted review feedback state tied to
the authoritative summary comment.

Not:

- raw markdown alone
- dashboard markdown
- free-form MR discussion text

Markdown note replies are the intake surface.
Structured stored feedback is the authoritative machine-facing record.

This product contract should be shared across both GitLab and GitHub.

Only the provider-specific note fetching and reply retrieval surfaces should
change across platforms.

## Risks

### Feedback scope drift

If the feature expands beyond change-request scope too early, it can turn local operator
feedback into unsafe global suppression.

### Parsing ambiguity

If the bounded reply syntax is too flexible, the intake path becomes hard to
trust.

### Overloading the dashboard

If this feature is pushed into the dashboard instead of review reconciliation,
it will blur boundaries and make the workflow harder to reason about.

## Acceptance Criteria

This design is successful when:

- an operator can mark a numbered finding on one change request as `incorrect`
  `out_of_scope`, or `accepted`
- the feedback is stored as structured change-request-scoped state
- later review passes on that same change request can use the feedback during
  reconciliation
- the feature does not change core review analysis behavior
- the feature does not create global suppression outside the change request
- the dashboard remains optional for visibility rather than the authoritative
  storage layer
