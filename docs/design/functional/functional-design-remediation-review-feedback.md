# Remediation Review Feedback Functional Design

## Purpose

Define the operator-controlled path for correcting a remediation change request
when ZeroOne Ops review publishes actionable findings. The path applies equally
to GitHub pull requests and GitLab merge requests.

The review result is evidence about a proposed remediation change. It is not a
new source finding and must not be routed through finding sync or treated as a
fresh unlinked remediation candidate.

## Goals

- make actionable remediation-review feedback visible and stateful;
- preserve the work item, linked change request, and review evidence;
- let an authorized operator request one bounded revision of the existing
  change request;
- preserve the existing one-file patch, validation, and publication safeguards;
- keep GitHub and GitLab operator behavior equivalent.

## Non-Goals

- automatically retrying a remediation after review findings;
- reopening a closed or merged change request;
- creating a new branch or change request for review feedback;
- multi-file corrective edits, review-comment parsing, or free-form operator
  instructions;
- changing finding-sync, policy, capacity, or normal blocked-work recovery.

## Work-Item States

Two open work-item states extend the existing state projection:

| Status | Meaning | Provider issue state |
|---|---|---|
| `review_feedback_required` | A linked, open remediation change request received review findings and awaits an operator decision. | open |
| `review_revision_queued` | An authorized operator requested a bounded revision of the linked change request. | open |

Both states retain the linked change request, remain visible in the active
operator queue, and consume remediation capacity. They are not `blocked`,
`dismissed`, `candidate`, or `approved` work.

## Review Projection Rules

When review is published against a linked remediation change request:

| Review classification | Work-item effect |
|---|---|
| `findings_present` | Persist bounded review evidence and move the item to `review_feedback_required`. |
| `no_findings` | Persist review evidence and retain normal linked-change-request lifecycle behavior. |
| `manual_review_only` | Persist review evidence but do not queue a revision. |

The projected evidence contains the reviewed SHA, review-note reference,
summary, finding count, and a bounded structured representation of the
actionable findings. It is displayed for operators and supplied to a later
revision as untrusted evidence. The change request remains the complete
human-readable review record.

`findings_present` is actionable only when it includes a valid bounded feedback
packet. A malformed or absent packet is projected as `manual_review_only` with
a warning, not as a requeueable state. A `manual_review_only` result never
clears existing actionable feedback: it preserves
`review_feedback_required` when that state already exists, and otherwise only
updates review evidence.

A review projection is accepted only when its reviewed SHA remains the current
linked PR/MR head and is not older than the persisted projection. An older or
otherwise stale review cannot overwrite newer feedback or a queued revision.

A newer review projection supersedes any queued revision request. If a review
arrives while the item is `review_revision_queued`, the item returns to
`review_feedback_required` with the newer reviewed SHA and evidence. The prior
operator command cannot revise against stale feedback.

## Operator Flow

An authorized operator reviews the remediation PR/MR and its projected review
evidence. For `review_feedback_required`, the work-item view renders the
provider-native command:

```text
/zeroone remediation requeue
```

The command requests a revision; it does not immediately generate code. The
normal remediation workflow later claims `review_revision_queued` work and is
the only component allowed to edit code, validate, commit, push, or update the
change request.

The same command remains state-aware. On `blocked` work it uses the existing
recovery flow; on `review_feedback_required` work it queues a same-branch
revision; all other statuses reject it. A command on the PR/MR, operational
summary, or another non-work-item surface is never authoritative.

The linked PR/MR review summary must direct operators to the authoritative
work-item issue when review feedback requires action. It includes a compact
link to that issue and states that requeue commands are accepted there, not on
the PR/MR. The work-item issue renders the `review_feedback_required` status,
the linked PR/MR, bounded projected findings, and the exact requeue command.
The operational summary remains an inspection surface: it may link to the
active PR/MR and show the feedback-required status, but it does not accept
commands.

There is no `dismiss` action while the linked PR/MR remains open. An operator
who decides not to pursue the change closes the PR/MR through the provider;
the existing lifecycle flow then moves the work item to `blocked`, where the
existing requeue or dismiss recovery choices apply.

## Same-Change-Request Revision

Before queuing or executing a revision, ZeroOne Ops verifies that:

1. the linked PR/MR is still open;
2. its source branch is available; and
3. its current head SHA exactly equals the SHA reviewed in the projected
   feedback.

If any condition fails, no code is changed. The operator command is rejected
as stale and the item remains `review_feedback_required` until a current review
result is projected.

For a valid queued revision, the remediation workflow checks out the verified
branch before reading code or repository guidance. Unavailable context restores
`review_feedback_required` with execution evidence; it never becomes ordinary
blocked work. Dry runs inspect eligibility without modifying the checkout.
The workflow uses the verified existing source branch. It generates and applies
only a patch within the
original remediation target file, regardless of locations mentioned in review
feedback. It runs the configured validation safeguards and pushes only a normal
fast-forward commit. The existing PR/MR is updated; no second change request
is created.

If the remote branch changes before push, a non-fast-forward failure is treated
as stale feedback. The revision does not overwrite the branch and returns to
`review_feedback_required` with bounded execution evidence.

## Failure And Lifecycle Rules

- A successful revision returns the item to `in_progress`, clears the queued
  revision marker, and retains the projected review evidence until a newer
  review supersedes it. The normal PR/MR review trigger then evaluates the new
  revision; no automatic requeue occurs.
- A failed, rejected, invalid-scope, or stale revision returns the item to
  `review_feedback_required` with existing bounded last-execution evidence.
- In revision mode, a semantic-safety rejection is revision failure evidence,
  not a terminal dismissal. The linked PR/MR and actionable review feedback
  remain available for the operator to resolve manually or requeue after a
  newer review.
- Lifecycle reconciliation must preserve `review_feedback_required` and
  `review_revision_queued` while the linked PR/MR is open. It must not rewrite
  them to ordinary `in_progress`.
- A stale revision claim returns to `review_feedback_required` with bounded
  recovery evidence. It must never become ordinary `approved` work.
- Merged and closed-unmerged PR/MR handling remains lifecycle-owned. Once the
  request is no longer open, this design does not reuse it.
- Repeated revisions require a new explicit operator command after each review
  result. There is no automatic feedback loop in v1.
- V1 reuses the existing read-before-write protection for work-item claims. It
  does not claim provider-bound compare-and-set semantics; a later atomic-claim
  slice remains responsible for that stronger concurrency guarantee.

## Provider Parity And Authorization

GitHub accepts the command only from the existing authorized work-item issue
comment boundary. GitLab accepts it only from the existing authorized work-item
issue-note polling boundary. The shared decision logic receives the authorized
request and provider-neutral work-item state; provider clients own comment
transport, PR/MR lookup, branch operations, and issue rendering.

Provider labels and issue open/closed state remain derived indexes. Persisted
machine state is authoritative for the feedback status, reviewed SHA, and
revision decision.

## Acceptance Criteria

- A remediation review with findings moves only its linked work item to
  `review_feedback_required`.
- An authorized requeue updates the same open PR/MR branch only after the
  reviewed-head verification passes.
- A stale command, changed branch, closed request, or failed revision cannot
  overwrite provider state or create a fresh PR/MR.
- Review evidence and execution evidence remain visible on both providers.
- Active review-feedback work remains capacity-protected until merged, closed,
  or explicitly resolved through the existing lifecycle and recovery flows.
