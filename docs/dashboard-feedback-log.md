# Dashboard Feedback Log

Use this log during live testing to capture concrete dashboard and
dashboard-adjacent operator workflow outcomes, group them by operator-facing
pattern, and decide whether the right response is dashboard wording, policy
behavior, reconciliation, or documentation.

## How To Use

For each notable dashboard or operator-surface outcome, add one row with:

- the dashboard item, merge request, or run reference
- whether the outcome itself was correct
- the main operator or workflow pattern
- a short note about why
- the chosen action

Suggested action values:

- `docs`
- `dashboard wording`
- `policy`
- `remediation logic`
- `reconciliation`
- `observability`
- `no change`

Suggested status values:

- `new`
- `tracking`
- `patched`
- `implemented`
- `validated`
- `closed`

## Log

| Date | Item / Run | Pattern | Valid? | Assessment | Action | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-05 | Failed dashboard remediation/reconciliation items after GitLab token expiry | `Investigate Failure` recovery path is unclear for operators | yes | The failed state is understandable, but the operator-facing dashboard does not yet make it clear how to recover when failure was caused by infrastructure or credential issues such as an expired GitLab token | dashboard wording + docs + policy | tracking | Example: multiple items remain in `Investigate Failure` after a token outage, and the operator needs a clear reset/retry story instead of guessing whether to edit state, rerun reconciliation, or wait for automation. |
| 2026-05-05 | Retry-eligible and failed dashboard items | Retry explanation is not yet a first-class operator surface | yes | Operators can see retry-relevant state today, but the dashboard does not yet explain retryability and block reasons as clearly or intentionally as policy commands explain policy changes | dashboard wording + policy + docs | tracking | A lightweight explanation surface should likely come before any reset/requeue command so operators first understand why an item is blocked, retryable, or failed. |
| 2026-05-05 | Merge requests with multiple review passes | Repeated MR reviews are not grouped clearly on the dashboard | yes | When one merge request receives multiple review passes, the dashboard still presents them as separate review entries instead of one grouped MR-centric review history, which makes repeated-review state harder to scan | dashboard wording + rendering | tracking | Operators should be able to understand the latest review state plus compact continuity outcomes for one MR without mentally joining several separate review rows. |

## Pattern Notes

### `Investigate Failure` Recovery Path Is Unclear

- Typical shape:
  - a dashboard item lands in `Investigate Failure` for an operational reason
    such as expired credentials, inaccessible GitLab metadata, or another
    external-system failure
  - the operator can see that something failed, but not how to recover the
    item cleanly
- Preferred response:
  - make the failure reason more explicit in dashboard-visible state
  - explain whether the item is retryable, blocked, or needs operator action
  - document the recommended recovery path for common failure classes such as
    credential expiry or temporary API access failures
  - later, consider a more explicit reset/requeue operator path if manual
    recovery remains too ambiguous

### Retry Explanation Is Not Yet A First-Class Operator Surface

- Typical shape:
  - the dashboard carries retry-related state such as retry eligibility or
    block reasons, but operators do not yet have a crisp, intentional surface
    for understanding why an item can retry, cannot retry, or needs review
- Preferred response:
  - make retry explanation more explicit in dashboard rendering and operator
    guidance
  - prefer explanation-first improvements before adding new reset/requeue
    commands
  - if later needed, add a bounded retry-explanation operator command before
    adding mutable retry-reset actions

### Repeated MR Reviews Are Not Grouped Clearly

- Typical shape:
  - one merge request receives multiple review passes, but the dashboard shows
    them as separate review entries instead of a grouped MR-centric sequence
- Preferred response:
  - group repeated reviews by merge request
  - show the latest review state as the primary row
  - attach compact continuity outcomes such as unresolved, new, or no longer
    present once that summary is trustworthy enough to present
