# Functional Design: PR Review Operator Feedback

## Purpose

Add a lightweight, structured way for operators or developers to mark a review
finding on one merge request as invalid, accepted, or unclear.

The goal is to close the missing feedback loop in the review workflow without
changing the review bot's analysis behavior or introducing global memory.

This design should make repeated reviews on the same merge request feel more
collaborative and less stubborn when a human has already corrected the bot.

## Problem

The current review flow can:

- generate review findings
- persist prior review state
- reconcile repeated passes on the same merge request

But it still cannot absorb a simple human correction such as:

- this finding is invalid
- this concern is accepted
- this note is unclear

That leaves the workflow with an important gap:

- the bot can speak
- the human can disagree
- but the system does not yet store or apply that disagreement in a structured
  way on later passes of the same merge request

## Goal

Introduce bounded MR-scoped operator feedback for numbered review findings so
that:

- operators can respond to one finding with a short structured command
- the feedback is stored as structured state
- later review passes on the same merge request can acknowledge or suppress the
  same concern when appropriate
- the feedback loop improves trust without changing core review judgment logic

## Non-Goals

- no global suppression across merge requests or repositories
- no natural-language interpretation of arbitrary free-form comments in v1
- no dashboard-owned source of truth for review feedback
- no rewriting of historical review notes
- no direct modification of the underlying review analysis result
- no requirement to infer feedback from reactions, emojis, or broad discussion

## Boundaries

### 1. Merge-request scoped only

Feedback belongs to one merge request.

That means:

- feedback should only affect later review passes on that same merge request
- feedback should not be treated as repository-wide truth
- one developer marking a finding invalid on one merge request must not teach
  the bot to suppress that finding everywhere else

### 2. Structured commands only in v1

The first version should only accept short structured feedback commands.

Recommended early examples:

- `1 invalid`
- `2 accepted`
- `3 unclear`

This keeps intake deterministic and easy to test.

### 3. Review reconciliation owns the feature

The source of truth for this feature should live with review reconciliation and
review state, not with the dashboard.

The dashboard may later mirror a high-level summary such as:

- feedback received
- number of invalidated findings

But it should not own the authoritative feedback record.

### 4. Numbered findings are required

Review notes should expose stable finding numbers within one review note so that
operators can refer to a finding without needing to quote large text blocks.

Those numbers are local to the reviewed note or reviewed SHA and should be used
alongside merge request and review revision context when storing feedback.

### 4a. Latest review note only

Only the latest review note for the relevant reviewed revision should be
authoritative for feedback intake.

That means:

- feedback should not be collected from arbitrary older bot notes on the same
  merge request
- numbering only needs to stay stable within the latest relevant review note
- later note parsing should prefer one clear authoritative note rather than
  trying to merge feedback from multiple historic review threads

## Desired Outcome

Repeated reviews on the same merge request should feel more like:

- this concern was reported earlier and still appears unresolved
- this concern was reported earlier but no longer appears present
- this concern was previously marked invalid on this merge request
- this is a new concern in this pass

rather than:

- the bot re-reporting the same rejected finding as if it were brand new

## Functional Direction

### 1. Structured feedback intake

Operators should be able to leave one short structured reply against the
review note itself.

The workflow should:

- detect the merge request and reviewed revision
- read feedback only from the review note thread or reply surface
- identify the referenced finding number
- parse the bounded feedback command
- store the result as structured review feedback

The intake path should only accept a strict allowlisted command shape in v1.

That means:

- only bounded commands such as `1 invalid` or `2 accepted` should be parsed as
  structured feedback
- malformed commands such as `1 invalid because...` should be ignored unless
  they match the strict allowlist exactly
- arbitrary free-form comment text should be ignored by the structured intake
  path
- the bot should not attempt to infer feedback intent from surrounding
  discussion, quoted text, or unsafe input

### 2. Minimal feedback vocabulary

The first feedback vocabulary should stay very small.

Recommended first values:

- `invalid`
- `accepted`

Why this set:

- `invalid` captures clear disagreement
- `accepted` captures operator agreement or acknowledgement
- keeping the vocabulary smaller in v1 reduces ambiguity and parser surface

### 2a. Operator prompting in the review note

The review note itself should teach the reply format when numbered findings are
present.

The first version should include one short instruction block near the end of
the note, for example:

- `1 invalid`
- `2 accepted`
- `3 unclear`

The note should also state that this feedback is scoped to the current merge
request only.

This keeps discovery close to the workflow and avoids requiring operators to
learn the format from separate documentation first.

### 3. Structured persisted state

Feedback should be stored in a structured machine-friendly form linked to:

- merge request iid
- reviewed head SHA or review revision key
- finding number within the reviewed note
- canonical finding identity when available
- feedback type
- author metadata
- timestamp

In v1, any merge-request participant may provide valid structured feedback.

This should make later reconciliation deterministic.

### 4. Follow-up reconciliation behavior

Later review passes on the same merge request should use stored operator
feedback conservatively.

Examples:

- if the same finding returns and earlier feedback marked it `invalid`, the bot
  should not present it as a brand-new concern; it should acknowledge that the
  concern was previously disputed on this merge request
- if the same finding returns and earlier feedback marked it `accepted`, the
  bot may acknowledge prior agreement if useful
- when multiple valid feedback commands exist for the same finding target, the
  latest valid feedback should win

The exact note wording can stay flexible, but the behavior should be grounded in
structured state.

### 5. Separation from analysis

This feature should not alter the underlying review model or its raw output.

Instead:

- analysis still produces a review result
- reconciliation later compares that result to prior review state plus operator
  feedback
- note rendering then decides how to present still-open, resolved, invalidated,
  or new concerns

This keeps the feedback loop additive and bounded.

## Source Of Truth

The source of truth should be structured persisted review feedback state.

Not:

- raw markdown alone
- dashboard markdown
- free-form MR discussion text

Markdown note replies are the intake surface.
Structured stored feedback is the authoritative machine-facing record.

## Risks

### Feedback scope drift

If the feature expands beyond MR scope too early, it can turn local operator
feedback into unsafe global suppression.

### Parsing ambiguity

If the accepted feedback syntax is too flexible, the intake path becomes hard to
trust.

### Overloading the dashboard

If this feature is pushed into the dashboard instead of review reconciliation,
it will blur boundaries and make the workflow harder to reason about.

## Acceptance Criteria

This design is successful when:

- an operator can mark a numbered finding on one merge request as `invalid`
  or `accepted`
- the feedback is stored as structured MR-scoped state
- later review passes on that same merge request can use the feedback during
  reconciliation
- the feature does not change core review analysis behavior
- the feature does not create global suppression outside the merge request
- the dashboard remains optional for visibility rather than the authoritative
  storage layer
