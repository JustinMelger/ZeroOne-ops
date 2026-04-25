# Incremental PR Review Memory Functional Design

## 1. Purpose

Improve the review bot so repeated reviews on the same merge request feel
incremental rather than stateless.

The bot should use its own prior review output on the same merge request as
bounded context for the next review pass. This should reduce repeated findings
after new commits are pushed and help the bot focus on what is new, unresolved,
or explicitly addressed.

## 2. Goals

- Reduce repeated review comments when the same merge request is reviewed again
  after new commits.
- Give the bot continuity across review passes on the same merge request.
- Help the bot distinguish:
  - previously reported findings that still appear unresolved,
  - findings that were addressed by later commits,
  - newly introduced findings since the last reviewed SHA.
- Keep the context bounded and predictable so review quality improves without
  turning the bot into an unbounded conversation history consumer.

## 3. Non-Goals

- Building full conversational memory for all historical review notes.
- Replacing merge request notes with dashboard-only review history.
- Automatically resolving or closing prior findings without a fresh review.
- Supporting arbitrary human review comments as trusted structured input.
- Creating a generalized long-term memory layer for all workflows in this
  phase.

## 4. Primary User Story

As a repository maintainer, when a merge request receives a second or third bot
review after new commits, I want the review to feel like a follow-up pass
instead of a brand-new review so the bot avoids repeating unchanged comments
and highlights what actually changed.

## 5. Assumptions

- The review bot can retrieve prior bot-authored notes or persisted review
  state for the same merge request.
- The bot already stores reviewed SHA and outcome information.
- Merge request notes remain the primary operator-facing review surface.
- The dashboard remains an optional traceability/control-plane surface rather
  than the sole source of review history.
- A bounded summary of prior bot reviews is enough for the first version.

Current first-version decisions:

- prior review memory should live first in persisted review state
- persisted GitLab notes may be used only as fallback reconstruction input
- prior findings should be stored as short normalized summaries rather than raw
  note bodies
- unchanged earlier findings should be framed as still unresolved when they
  remain important, not repeated as brand-new discoveries
- later no-findings passes may use concise language such as "no new actionable
  findings since the last reviewed SHA" when a note is published
- prior review memory should be used mainly for prompt context, with only light
  incremental framing in rendered output
- only prior reviews authored by this bot and present in persisted state should
  be included
- bounded history should be trimmed by prior review pass count, not by total
  prior findings
- repeated-finding behavior should stay conservative and hardcoded in the first
  version rather than becoming a separate policy knob

## 6. Functional Summary

For repeated reviews on the same merge request:

1. identify prior bot reviews for the same MR,
2. select a bounded subset of recent prior review passes,
3. convert them into compact structured prior-review context,
4. include that context in the next review analysis prompt,
5. instruct the model to avoid repeating unchanged findings unless they remain
   important and unresolved,
6. render the new note so it reads like an incremental review pass.

## 7. Proposed Behavioral Rules

### 7.1 First Review On A Merge Request

- Behaves like the current review flow.
- No prior review context is included.

### 7.2 Repeated Review On The Same Merge Request

- Include bounded prior bot review context for that MR.
- Prefer the most recent prior reviewed SHA first.
- Keep the first version small, with a conservative default of the last `2`
  prior review passes.
- Make this bounded history window configurable as
  `review.max_prior_review_passes`.

### 7.3 Repetition Handling

The bot should:

- avoid re-reporting the same unchanged finding as if it were new,
- call out when an earlier finding still appears unresolved,
- call out when a finding seems newly introduced since the last reviewed SHA,
- avoid turning the note into a long history recap.

### 7.4 Trust Boundaries

- Prior bot reviews are machine context, not source-of-truth evidence.
- The current diff and repository code remain the primary evidence surface.
- Prior review memory should guide prioritization and phrasing, not override the
  current code-backed review judgment.

## 8. Functional Requirements

### 8.1 Prior Review Retrieval

The workflow must be able to retrieve prior bot review context for the current
merge request.

The first version should prefer:

- persisted structured review state,
- prior bot-authored MR notes only when needed to reconstruct bounded context.

The number of prior review passes included should be bounded by
`review.max_prior_review_passes`, defaulting to `2`.

### 8.2 Bounded Prior Review Context

The next review pass should include only a compact structured summary such as:

- prior reviewed SHA,
- prior review classification,
- prior findings count,
- short prior summary,
- bounded prior findings list or normalized finding summaries.

The first version should not inject full raw note history into the prompt.
The count of prior passes included should be configurable through
`review.max_prior_review_passes`.

### 8.3 Incremental Review Prompting

The review prompt should instruct the model to:

- treat prior review memory as context,
- prefer new or still-unresolved findings,
- avoid repeating the same finding without new evidence or a clear unresolved
  status.

### 8.4 Operator-Facing Output

The review note should remain concise and focused on the current review pass.

The first version may include light incremental framing such as:

- previously reported concern still appears unresolved,
- no new actionable findings beyond earlier comments,
- new finding since the last reviewed SHA.

This light follow-up language is important for trust: the note should feel like
an incremental review pass rather than a stateless rerun, even though the main
evidence still comes from the current diff and code.

## 9. Workflow Ownership

- Review owns prior-review retrieval, normalization, and use in the next review
  pass.
- The dashboard may mirror review history later, but it should not become the
  only review-memory source in this phase.
- Reconciliation and remediation do not own repeated-review memory for normal
  merge request review passes.

## 10. First Version Scope

The first version should stay conservative:

- same merge request only,
- bot-authored prior reviews only,
- bounded recent history only, with `review.max_prior_review_passes`
  defaulting to `2`,
- no cross-MR memory,
- no human-comment ingestion,
- no automatic finding resolution model.

## 11. Success Criteria

- repeated reviews on the same MR become less repetitive,
- operators can more easily tell what is new versus previously reported,
- review trust improves because follow-up passes feel incremental,
- the added context stays bounded and does not noticeably increase prompt noise.
