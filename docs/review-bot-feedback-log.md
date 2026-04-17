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
| 2026-04-17 |  | Unsupported path treated as regression |  |  |  |  | Example: review assumes a `None` or missing-input path even though the visible schema forbids it. |
| 2026-04-17 |  | Config/runtime shape overclaimed |  |  |  |  | Example: review treats a config-derived symbol as a mapping/object even though runtime resolution is unclear or resolves to a scalar. |
| 2026-04-17 |  | Summary introduced unproven concern |  |  |  |  | Example: findings are reasonable, but the summary adds a claim not actually supported by the findings. |
| 2026-04-17 |  | Contract change valid |  |  |  |  | Example: field-name compatibility is preserved but legacy accepted values are no longer accepted. |
| 2026-04-17 |  | Code smell overstated as runtime bug |  |  |  |  | Example: dead fallback logic or redundant cleanup is described as a supported-path regression without proof. |
| 2026-04-17 |  | Too verbose |  |  |  |  | Example: review repeats the same point across summary, evidence, and follow-up. |
| 2026-04-17 |  | Header tone too robotic |  |  |  |  | Example: `AI Review Summary` feels impersonal and not aligned with a conversational review style. |
| 2026-04-17 |  | Conversational greeting using MR author |  |  |  |  | Example: prefer `Hi <MR author>,` with `Hi,` as a fallback before the review summary. |

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
