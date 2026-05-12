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
| 2026-05-05 | Failed dashboard remediation/reconciliation items after GitLab token expiry | `Investigate Failure` recovery path is unclear for operators | yes | The dashboard now surfaces clearer recovery-oriented wording for retry-ready, retry-blocked, and likely operational failures, but a richer operator reset/requeue surface is still deferred | dashboard wording + docs + policy | implemented | Current board wording improves failure diagnosis; later explicit reset/requeue controls can still be added if operators keep needing manual recovery help after outages. |
| 2026-05-05 | Retry-eligible and failed dashboard items | Retry explanation should be more intentional for operators | yes | The dashboard now distinguishes retry-eligible and retry-blocked failed items in the main workflow board, so explanation is materially better even though no separate command surface exists yet | dashboard wording + policy + docs | implemented | Explanation-first improvements shipped before any mutable reset/requeue command surface. |
| 2026-05-05 | Merge requests with multiple review passes | Repeated MR reviews should collapse into one clearer MR-centric history | yes | The dashboard now groups repeated review passes by MR and shows the latest review state as the main visible row, while keeping richer continuity summaries as a later refinement | dashboard wording + rendering | implemented | Compact unresolved/new/no-longer-present continuity summaries are still deferred until the projection is trustworthy enough to surface. |
| 2026-05-07 | Manual-review-only remediation outcome visibility on workflow board | `Needs Attention` is mixing automation queue items with human-follow-up items | yes | The workflow board is now split into clearer buckets such as `Queue Auto-fix`, `Needs Review`, `In Flight`, `Completed`, and `Dismissed`, so manual-follow-up items no longer disappear or pollute the main automation queue | dashboard rendering + wording | implemented | A later `Blocked` bucket can still be considered if real operator usage shows it would improve scanability. |
| 2026-05-07 | Failed workflow items after operator inspection | `Investigate Failure` does not yet imply a clear next recovery action | yes | The board now makes the likely next step clearer through retry-ready, retry-blocked, and investigation-oriented wording, but future mutable operator actions are still intentionally deferred | dashboard wording + policy + docs | implemented | The operator surface now answers “what likely happened next?” better than before; later reset/requeue controls can build on that clearer explanation model. |

## Pattern Notes

### `Investigate Failure` Recovery Path Is Unclear

- Typical shape:
  - a dashboard item lands in `Investigate Failure` for an operational reason
    such as expired credentials, inaccessible GitLab metadata, or another
    external-system failure
  - the operator can see that something failed, but not how to recover the
    item cleanly
- Preferred response:
  - implemented clearer failure reason and retry/block wording in the workflow
    board
  - keep documenting common recovery paths for operational failures such as
    credential expiry or temporary API access failures
  - later, consider a more explicit reset/requeue operator path if manual
    recovery remains too ambiguous

### Retry Explanation Should Be More Intentional For Operators

- Typical shape:
  - the dashboard carries retry-related state such as retry eligibility or
    block reasons, but operators do not yet have a crisp, intentional surface
    for understanding why an item can retry, cannot retry, or needs review
- Preferred response:
  - implemented explanation-first retry wording in the dashboard rendering
  - continue refining operator guidance before adding new reset/requeue
    commands
  - if later needed, add a bounded retry-explanation operator command before
    adding mutable retry-reset actions

### Repeated MR Reviews Should Collapse Into One Clearer MR-Centric History

- Typical shape:
  - one merge request receives multiple review passes, but the dashboard shows
    them as separate review entries instead of a grouped MR-centric sequence
- Preferred response:
  - implemented grouped review history by merge request
  - show the latest review state as the primary row
  - later, attach compact continuity outcomes such as unresolved, new, or no
    longer present once that summary is trustworthy enough to present

### Workflow `Needs Attention` Is Mixing Different Kinds Of Work

- Typical shape:
  - the workflow board shows open auto-fix candidates, failed automation
    outcomes, and manual-review-only remediation outcomes in one shared
    operator-facing area
  - this makes the board less scannable because "things the bot can queue now"
    and "things a human must inspect now" are not the same kind of work
- Preferred response:
  - implemented a split into clearer buckets such as:
    - `Queue Auto-fix`
    - `Needs Review`
    - `In Flight`
    - `Completed`
    - `Dismissed`
  - make the workflow surface distinguish between automation-ready items and
    human-follow-up items instead of merging them under one broad label

### `Investigate Failure` Should Point More Clearly Toward Recovery

- Typical shape:
  - a workflow item fails for an operational or validation reason
  - the operator investigates and understands the failure cause
  - but the dashboard still does not make the next action explicit enough
- Preferred response:
  - implemented clearer diagnosis and next-step wording in the workflow board
  - keep distinguishing diagnosis from recovery, for example:
    - rerun after fixing environment or credentials
    - leave blocked by review or policy
    - move to manual follow-up
    - retry automation when the blocker is resolved
  - continue improving failure explanation together with next-step clarity,
    not as separate unrelated concerns
