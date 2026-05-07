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
| 2026-05-05 | Failed dashboard remediation/reconciliation items after GitLab token expiry | `Investigate Failure` recovery path is unclear for operators | yes | The first dashboard wording pass is now in place: failed items can surface clearer retry-eligible and retry-blocked wording, but the broader operator recovery story is still incomplete for infrastructure failures such as expired GitLab tokens | dashboard wording + docs + policy | tracking | Example: multiple items remain in `Investigate Failure` after a token outage, and the operator still needs a clearer reset/retry story instead of guessing whether to edit state, rerun reconciliation, or wait for automation. |
| 2026-05-05 | Retry-eligible and failed dashboard items | Retry explanation is not yet a first-class operator surface | yes | The dashboard now distinguishes retry-eligible and retry-blocked failed items more clearly in visible wording, but the explanation surface is still not as intentional or complete as the policy command surface | dashboard wording + policy + docs | tracking | A lightweight explanation surface should still come before any reset/requeue command so operators understand why an item is blocked, retryable, or failed. |
| 2026-05-05 | Merge requests with multiple review passes | Repeated MR reviews are not grouped clearly on the dashboard | yes | When one merge request receives multiple review passes, the dashboard still presents them as separate review entries instead of one grouped MR-centric review history, which makes repeated-review state harder to scan | dashboard wording + rendering | tracking | Operators should be able to understand the latest review state plus compact continuity outcomes for one MR without mentally joining several separate review rows. |
| 2026-05-07 | Manual-review-only remediation outcome visibility on workflow board | `Needs Attention` is mixing automation queue items with human-follow-up items | yes | The immediate visibility bug can be patched so manual-review-only outcomes do not disappear, but the broader board structure is still unclear: the same `Needs Attention` area is currently trying to represent both queueable auto-fix work and items that require explicit human review or investigation | dashboard rendering + wording | tracking | A cleaner long-term shape is likely to separate `Queue Auto-fix` from `Needs Review` or `Review / Investigate`, so operators can tell at a glance what the bot can act on versus what needs a human. |
| 2026-05-07 | Failed workflow items after operator inspection | `Investigate Failure` does not yet imply a clear next recovery action | yes | `Investigate Failure` is a reasonable diagnosis step, but after the operator understands the cause the dashboard still does not make the resolution step explicit enough: rerun automation, fix environment/config, treat as manual follow-up, or leave blocked | dashboard wording + policy + docs | tracking | The operator surface should help answer not only "what failed?" but also "what should I do next now that I understand the failure?" |

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
  - keep iterating after the first wording pass so operational failures such as
    expired credentials have a clearer recovery story
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
  - continue improving retry explanation in dashboard rendering and operator
    guidance after the first wording pass
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

### Workflow `Needs Attention` Is Mixing Different Kinds Of Work

- Typical shape:
  - the workflow board shows open auto-fix candidates, failed automation
    outcomes, and manual-review-only remediation outcomes in one shared
    operator-facing area
  - this makes the board less scannable because "things the bot can queue now"
    and "things a human must inspect now" are not the same kind of work
- Preferred response:
  - keep short-term visibility fixes so important items do not disappear
  - later split the board into clearer buckets such as:
    - `Queue Auto-fix`
    - `Needs Review` or `Review / Investigate`
    - `In Flight`
    - `Completed`
  - make the workflow surface distinguish between automation-ready items and
    human-follow-up items instead of merging them under one broad label

### `Investigate Failure` Does Not Yet Imply A Clear Recovery Path

- Typical shape:
  - a workflow item fails for an operational or validation reason
  - the operator investigates and understands the failure cause
  - but the dashboard still does not make the next action explicit enough
- Preferred response:
  - distinguish diagnosis from recovery
  - make the likely resolution path clearer after inspection, for example:
    - rerun after fixing environment or credentials
    - leave blocked by review or policy
    - move to manual follow-up
    - retry automation when the blocker is resolved
  - continue improving failure explanation together with next-step clarity,
    not as separate unrelated concerns
