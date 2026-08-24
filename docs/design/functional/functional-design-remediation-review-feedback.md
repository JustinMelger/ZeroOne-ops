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
existing source branch. It generates and applies only a patch within the
original one-file scope, runs the configured validation safeguards, and pushes
only a normal fast-forward commit. The existing PR/MR is updated; no second
change request is created.

If the remote branch changes before push, a non-fast-forward failure is treated
as stale feedback. The revision does not overwrite the branch and returns to
`review_feedback_required` with bounded execution evidence.

## Failure And Lifecycle Rules

- A successful revision returns the item to `in_progress`, clears the queued
  revision marker, and retains the projected review evidence until a newer
  review supersedes it.
- A failed, rejected, invalid-scope, or stale revision returns the item to
  `review_feedback_required` with existing bounded last-execution evidence.
- Lifecycle reconciliation must preserve `review_feedback_required` and
  `review_revision_queued` while the linked PR/MR is open. It must not rewrite
  them to ordinary `in_progress`.
- Merged and closed-unmerged PR/MR handling remains lifecycle-owned. Once the
  request is no longer open, this design does not reuse it.
- Repeated revisions require a new explicit operator command after each review
  result. There is no automatic feedback loop in v1.

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
