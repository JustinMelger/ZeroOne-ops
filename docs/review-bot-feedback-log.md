# Review Bot Feedback Log

Use this log during live testing to capture concrete review outcomes, group
them by pattern, and decide whether the right response is a prompt change,
better context, validator work, or no change.

## How To Use

For each notable review outcome, add one row with:

- the merge request or commit reference
- whether the concern was valid
- the main pattern
- a short note about why
- the chosen action

Suggested action values:

- `prompt`
- `context`
- `validator`
- `docs`
- `code clarity`
- `no change`

Suggested status values:

- `new`
- `tracking`
- `patched`
- `implemented`
- `validated`
- `closed`

## Log

| Date | MR / Commit | Pattern | Valid? | Assessment | Action | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-04-17 |  | Unsupported path treated as regression |  | Repeated but narrower after prompt/context improvements | prompt | tracking | Example: review assumes a `None` or missing-input path even though the visible schema forbids it. |
| 2026-04-17 |  | Config/runtime shape overclaimed |  | Improved, but still a live-testing watch item | prompt + context | tracking | Example: review treats a config-derived symbol as a mapping/object even though runtime resolution is unclear or resolves to a scalar. |
| 2026-04-17 |  | Summary introduced unproven concern |  | Staged reconciliation, artifact building, and validator gating were implemented from this feedback; keep validating live outputs | prompt + validator | implemented | Example: findings are reasonable, but the summary adds a claim not actually supported by the findings. |
| 2026-04-17 |  | Contract change valid | yes | Positive reference pattern to preserve | no change | validated | Example: field-name compatibility is preserved but legacy accepted values are no longer accepted. |
| 2026-04-17 |  | Code smell overstated as runtime bug |  | Improved, but still something to watch in live reviews | prompt | tracking | Example: dead fallback logic or redundant cleanup is described as a supported-path regression without proof. |
| 2026-04-17 |  | Too verbose |  | Better than before, but still under observation in live testing | prompt | tracking | Example: review repeats the same point across summary, evidence, and follow-up. |
| 2026-04-18 |  | Repeated review does not acknowledge earlier review clearly enough |  | Continuity-aware staged review flow and overlap follow-up support were implemented from this feedback; still validate the note quality in live testing | prompt + context + code | implemented | Example: a later review reads like a fresh isolated pass instead of clearly acknowledging what the bot said before. |
| 2026-04-17 |  | Header tone too robotic | yes | Replaced with a simpler conversational opener | docs | implemented | Example: `AI Review Summary` feels impersonal and not aligned with a conversational review style. |
| 2026-04-17 |  | Conversational greeting using MR author |  | Good later polish, but intentionally deferred | docs | tracking | Example: prefer `Hi <MR author>,` with `Hi,` as a fallback before the review summary. |
| 2026-04-20 | !376 / e47ba30b9e642e4ae4ae614fac15b0f851480a25 | Same-SHA review instability | no | Candidate/precision/validator staging was implemented from this feedback, but same-SHA stability still needs live-testing confirmation | validator + prompt + code | tracking | Same-SHA reruns should not behave like fresh stochastic reviews; treat this as a separate validation bucket from changed-SHA continuity. |
| 2026-04-20 | !376 / 0bf395931f2e712326d6ddff75f0484e0fa3fc1a | Missing inheritance or base-schema context | no | Review overclaimed a missing `customer_id` contract break even though the field is inherited from a base request model | context | tracking | Shared base classes or inherited schema fields still escape the visible local reasoning window in some reviews. |
| 2026-04-20 | !96 / e9a9a7c221c3480a1d671c449b8219d6fb755449 | Test inconsistency overstated as runtime regression | no | Review treated removal of one country skip as concrete unsupported-runtime evidence even though the visible implementation and config do not support that conclusion | prompt | tracking | Adjacent stale tests or inconsistent skips are not enough on their own to claim a production/runtime regression. |
| 2026-04-20 | !98 / 94fed6081726196e738c4952c20a73b6b888aab4 | Supported-path contract change overstated | no | Candidate and precision prompt discipline plus validator tightening were implemented from this feedback; keep watching live results | prompt + validator | implemented | Contract-change detection is useful, but the bot still sometimes overstates the pre/post behavior or affected surface. |
| 2026-04-20 | !382 / 9b2b597fe38ed7ae9249194d2293505d07fb9c8f | Verdict/reason contradiction | no | Implemented staged reconciliation plus validator downgrade from this feedback; keep watching for remaining contradiction cases during testing | validator + code | implemented | Output should be rejected when the rationale describes an actionable defect but the verdict is a clean pass. |
| 2026-04-22 |  | No-findings summary/reason still describes regression | no | Implemented validator downgrade and staged precision flow from this feedback; repair remains intentionally deferred until testing produces concrete cases | validator + code | implemented | Treat this as a reconciliation-owned consistency failure: downgrade or repair instead of publishing a normal clean-pass review. |
| 2026-04-23 | !389 / 1798e8ee4eed806c1e7b4cda27ff8d854573165a | No-findings summary/reason still describes regression | no | Implemented as part of the staged review and validator work; use future live examples to decide whether bounded repair is needed | validator + code | implemented | Another live occurrence of the same contradiction class: the model appears to detect a concern internally but still publishes a clean-pass verdict. |
| 2026-04-23 | !390 / 193968676c7295e058ad2d0da17f4c47f83705c1 | No-findings summary/reason still describes regression | no | Implemented as part of the staged review and validator work; future testing should confirm whether downgrade alone is sufficient before repair is added | validator + code | implemented | Count as the same reconciliation-validator need: the concern was present in the rationale but suppressed by final packaging/classification. |
| 2026-05-03 | !176 / 9449d598c0275ab0aa6052c3d4ad9470e599384b and !175 / b1c6c87bfaeeade8f59a17e9e1d6ce1aefe3d27b | No-findings explanation leaks pipeline internals | no | Review truth was fine, but the published clean-pass reasoning explained candidate-bounded precision mechanics instead of speaking in developer-facing code-review terms | prompt + artifact builder | tracking | Example: `The precision stage is bounded to the supplied candidate set` and `The grounded candidate set is empty` are internally true but poor operator-facing explanations. |
| 2026-05-03 | !176 / ec42036e45009d2a4167c267c0015b7b41e19874 | Prior concern incorrectly counted as new | no | Follow-up review said one earlier concern no longer appeared present while also claiming 2 new concerns, even though one of the two accepted findings was exactly the earlier unresolved concern | context + code | tracking | The next follow-up pass matched the surviving concern correctly, so the continuity/overlap path is close but still misclassifies some retained findings as newly introduced. |
| 2026-05-03 | !112 / 6240d3b6d9386bb4af0c72bfd7a3277fc600fa4b | Response-body truth overstated as HTTP response semantics | no | The finding was valid, but the published wording said the aggregate endpoint could yield an overall 200 response when the stronger visible claim is that the returned health payload/body can still report success | prompt + artifact builder | tracking | This should be phrased as a false healthy signal in the response body unless the review has direct evidence that the framework response status is also being set incorrectly. |
| 2026-05-03 | !112 / 6240d3b6d9386bb4af0c72bfd7a3277fc600fa4b rerun | No-findings explanation leaks pipeline internals | no | Rerun published a clean pass with precision-stage and grounded-candidate wording visible to developers even though those are internal control-path concepts | prompt + artifact builder | tracking | Same family as the other internal-language issue, but useful as a direct rerun example on a real merge request. |
| 2026-05-03 | !112 / 6240d3b6d9386bb4af0c72bfd7a3277fc600fa4b rerun | Same-SHA valid concern dropped on rerun | no | Earlier review found a valid health-endpoint issue on this exact SHA, but a later rerun on the same commit collapsed to `no_findings`, which is worse than the older continuity-only naming drift | prompt + context + code | tracking | Treat this as a stronger same-SHA regression example: the valid concern was not merely renamed or matched poorly, it disappeared from the grounded candidate set and final review entirely. |

## Pattern Notes

### Unsupported Path Treated As Regression

- Typical shape:
  - review assumes an input path that the visible schema or route contract does
    not support
- Preferred response:
  - prompt discipline
  - sometimes no change if the latest prompt already covers it and we are
    waiting for more signal

### Config/Runtime Shape Overclaimed

- Typical shape:
  - review infers a mapping/object runtime value from a helper/config symbol
    without visible proof of resolution
- Preferred response:
  - prompt discipline first
  - later, better helper-following or config-resolution context

### Summary Introduced Unproven Concern

- Typical shape:
  - findings are acceptable, but the summary or key reasoning mentions an extra
    unsupported issue
- Preferred response:
  - output-discipline prompt tightening
  - possible later validator support if it remains common

### Contract Change Valid

- Typical shape:
  - request/response contract really changed on a supported path
- Preferred response:
  - no suppression
  - keep as a positive example of a good review

### Code Smell Overstated As Runtime Bug

- Typical shape:
  - dead code, redundant fallback, or cleanup logic is reported as a concrete
    runtime regression without an affected supported path
- Preferred response:
  - prompt discipline
  - sometimes code cleanup separately if the smell is real

### Too Verbose

- Typical shape:
  - review says the same thing several times or spends too many words proving a
    narrow point
- Preferred response:
  - prompt concision
  - keep watching for whether verbosity is mostly in findings, summary, or both

### Repeated Review Does Not Acknowledge Earlier Review Clearly Enough

- Typical shape:
  - a repeated review note has access to prior-review context in theory, but
    the resulting note still reads too much like a fresh isolated pass
- Preferred response:
  - implemented staged continuity support, overlap-aware follow-up wording, and
    prior-review context handling
  - keep validating note quality during live testing
  - tighten prompt or overlap behavior only if the same weak continuity pattern
    keeps repeating

### Header Tone Too Robotic

- Typical shape:
  - the review header or opening label feels generic, product-like, or
    impersonal rather than teammate-like
- Preferred response:
  - output wording cleanup
  - likely docs/prompt-level presentation change rather than deeper review logic

### Conversational Greeting Using MR Author

- Typical shape:
  - the note should feel more like a teammate review and less like a system
    status block
- Preferred response:
  - use the merge request author's display name when available for a short
    greeting such as `Hi <name>,`
  - fall back to a neutral `Hi,` when author name is not available
  - keep the greeting short and use it only once at the top of the note

### Same-SHA Review Instability

- Typical shape:
  - the bot reviews the exact same merge-request SHA more than once and produces materially different findings or verdicts
- Preferred response:
  - implemented staged candidate/precision/validator separation to reduce
    compressed stochastic drift
  - track same-SHA drift separately from changed-SHA continuity during testing
  - distinguish continuity-only wording drift from more serious cases where a
    previously valid concern disappears entirely on a rerun of the same SHA
  - tighten validator or prompt behavior further if live reruns still drift too
    much

### Missing Inheritance Or Base-Schema Context

- Typical shape:
  - review reasons locally about one schema/router file and misses a required field or contract supplied by a shared base class or inherited model
- Preferred response:
  - improve context around inherited request/response models
  - be more conservative before claiming schema/contract regressions when inheritance is only partially visible

### Test Inconsistency Overstated As Runtime Regression

- Typical shape:
  - review interprets one changed or removed test skip as proof of runtime/platform support or regression without sufficient implementation evidence
- Preferred response:
  - prompt discipline
  - distinguish test-suite inconsistency from supported-path runtime behavior

### Supported-Path Contract Change Overstated

- Typical shape:
  - review spots a real contract-related change but overstates what behavior is newly allowed/forbidden or how widely the impact propagates
- Preferred response:
  - implemented candidate/precision prompt tightening and stricter staged
    review boundaries
  - keep watching whether pre/post behavior claims still overreach in live use

### Verdict/Reason Contradiction

- Typical shape:
  - the final verdict says `no actionable findings`, but the confidence reason or summary describes a deterministic or actionable defect
- Preferred response:
  - implemented validator rules and staged precision ownership of final review
    meaning
  - currently downgrade contradictory artifacts instead of publishing them
  - consider later bounded repair only after testing shows concrete recurring
    contradiction classes

### No-Findings Summary/Reason Still Describes Regression

- Typical shape:
  - classification is effectively a clean pass, but summary or confidence wording still talks about a regression or other actionable defect
- Preferred response:
  - implemented staged precision plus validator downgrade to
    `manual_review_only`
  - keep collecting live contradiction examples before adding bounded repair

### No-Findings Explanation Leaks Pipeline Internals

- Typical shape:
  - the published clean-pass review is correct, but the confidence reason
    explains internal staged-review mechanics instead of developer-facing review
    truth
- Preferred response:
  - keep pipeline-mechanics explanations in telemetry/debug surfaces, not the
    published review note
  - tighten prompt or artifact-builder wording so clean-pass explanations talk
    about the current diff and earlier concerns in code-review terms

### Response-Body Truth Overstated As HTTP Response Semantics

- Typical shape:
  - the review finding is valid, but the published wording overstates
    transport-level behavior such as HTTP status when the visible code more
    directly supports only a claim about the response payload/body
- Preferred response:
  - prefer the narrowest supported wording in published findings
  - keep response-body, return-value, and HTTP-status semantics distinct unless
    the visible code clearly proves all of them

### Prior Concern Incorrectly Counted As New

- Typical shape:
  - a follow-up review correctly keeps a prior concern alive, but continuity
    wording still counts it as a newly introduced concern instead of matching
    it to the earlier pass
- Preferred response:
  - keep hardening overlap/continuity matching with real examples
  - check whether the mismatch came from overlap candidate construction,
    precision interpretation of overlap hints, or later continuity attachment
