# PR Review Follow-Up Reconciliation Functional Design

## 1. Purpose

Improve repeated merge request reviews so the bot can explicitly recognize when
an earlier finding:

- still appears unresolved,
- appears resolved on a later SHA,
- or has been replaced by a different new concern.

The goal is to make repeated bot reviews feel more like a follow-up
conversation and less like stateless reruns.

## 2. Goals

- Make repeated review notes acknowledge earlier findings in a natural,
  bounded way.
- Distinguish between:
  - repeated unresolved findings,
  - previously reported findings that now appear resolved,
  - and newly introduced findings.
- Improve operator trust by making the bot visibly track the review thread over
  time.
- Keep the first version conservative and deterministic.

## 3. Non-Goals

- Building a global finding identity system across all merge requests.
- Supporting free-form human feedback as trusted finding state.
- Introducing a large new schema for finding relationships in the first
  version.
- Automatically closing findings outside a fresh review pass.

## 4. Primary User Story

As a maintainer reading a second or third bot review on the same merge request,
I want the bot to acknowledge whether an earlier concern still appears
unresolved or now appears resolved, so the review reads like an ongoing thread
instead of repeating the same message from scratch.

## 5. First-Version Assumptions

- Prior review memory for the same MR already exists in bounded structured
  state.
- Each prior review pass stores short normalized finding summaries.
- Merge request notes remain the primary operator-facing surface.
- A conservative summary-level and finding-level reconciliation is sufficient
  before adding richer schemas.

Agreed first-version decisions:

- reconcile only against the latest prior review pass
- use a conservative match based on file path, title, and normalized summary
- mention resolved earlier findings in both no-findings and new-finding follow
  ups when that improves continuity
- keep mixed resolved-plus-new summaries to one short line
- when resolution cannot be verified confidently from visible code, fall back to
  neutral follow-up wording or explicitly say that resolution could not be
  verified
- note wording is the first implementation target; structured result changes
  can come later if needed
- do not add an explicit stored finding fingerprint yet

## 6. Functional Summary

For a repeated review on the same merge request:

1. load the most recent prior review pass,
2. compare the current findings to the most relevant prior findings,
3. classify current review outcomes as:
   - still unresolved,
   - appears resolved,
   - new in this pass,
4. use that classification to shape the follow-up summary and finding wording.

## 7. Proposed Behavioral Rules

### 7.1 First Review On A Merge Request

- Behaves like the current baseline review flow.
- No follow-up reconciliation is needed.

### 7.2 Repeated Review With The Same Concern Still Present

- Do not phrase the concern as a fresh discovery.
- Acknowledge that the earlier concern still appears unresolved.
- Keep the repeated wording shorter than the first report where possible.

Example direction:

- `Follow-up review: the earlier concern about X still appears unresolved.`

### 7.3 Repeated Review Where The Earlier Concern No Longer Appears Present

- Explicitly acknowledge that the earlier concern now appears resolved.
- If no new issues are found, the note should say so.

Example direction:

- `Follow-up review: the earlier concern about X no longer appears present.`
- `No new actionable findings in this review pass.`

### 7.4 Repeated Review With A Different New Concern

- Distinguish the new concern from the earlier one.
- Avoid implying that the new concern is just a restatement of the old one.
- Keep the follow-up summary to one short line when both a prior concern
  appears resolved and a different new concern appears.

Example direction:

- `Follow-up review: the earlier concern about X no longer appears present, but a new issue now appears around Y.`

### 7.5 Confidence And Uncertainty

- Follow-up reconciliation should improve wording and operator clarity, not
  invent certainty.
- If the bot cannot reliably tell whether a prior finding is resolved from the
  visible code, it should avoid claiming resolution too strongly.
- In ambiguous cases, it should fall back to neutral follow-up wording or
  explicitly say that resolution could not be verified rather than guessing.

## 8. Matching Strategy Expectations

The first version should use a conservative matching strategy based on bounded
structured finding information, such as:

- file path,
- finding title,
- and short normalized summary or evidence-adjacent text.

This matching should be good enough to support:

- same finding still present,
- same finding no longer present,
- clearly different finding.

It does not need to solve perfect finding identity in all cases.

If matching is weak or ambiguous, prefer under-matching and avoid strong
resolved wording.

## 9. Output Expectations

The operator-facing note should:

- mention prior findings only when that helps explain the current pass,
- remain concise,
- avoid turning into a full historical recap,
- and make the review feel like a continuation of the same thread.

The most important trust signals are:

- `still unresolved`
- `appears resolved`
- `new in this pass`
- `unable to verify whether the earlier concern is fully resolved`

## 10. First Version Scope

The first version should stay conservative:

- compare only against the latest prior review pass first,
- support summary-level and simple finding-level reconciliation,
- avoid a full per-finding relationship schema,
- keep the wording bounded and operator-friendly,
- avoid claiming resolution when visible code does not support it,
- use neutral or unable-to-verify wording when the match or resolution state is
  ambiguous.

## 11. Success Criteria

- repeated reviews on the same MR feel more conversational,
- repeated findings are no longer phrased as brand-new discoveries,
- resolved earlier findings are acknowledged when the visible code supports it,
- operators can more easily tell whether the bot is tracking progress across
  review passes.
