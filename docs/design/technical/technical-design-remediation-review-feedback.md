# Remediation Review Feedback Technical Design

## Scope

Implement the operator-controlled revision contract in
[functional-design-remediation-review-feedback.md](../functional/functional-design-remediation-review-feedback.md).

The shared work-item model owns feedback state and decision rules. GitHub and
GitLab adapters own provider transport, authorization, change-request lookup,
branch checkout, and issue projection. Finding sync remains out of scope.

## Shared State

Extend `WorkItemStatus` with `review_feedback_required` and
`review_revision_queued`. Both project to open provider issues and must be
included in active-remediation capacity accounting.

Extend `ProjectedReviewState` with a bounded `feedback` packet when
classification is `findings_present`. The packet should contain only the data
needed to explain and address the review:

- review summary and finding count;
- up to the configured review finding limit of structured finding entries;
- each entry's title, file path, line range, evidence, explanation, and
  suggested follow-up.

The packet must use the existing bounded review artifact, not parse published
Markdown. It is provider-neutral, persisted in the machine-state block, and
treated as untrusted data by remediation prompts.

Add a compact review-revision event or queued-revision marker carrying the
authorized command reference, actor, request time, and reviewed SHA. It allows
the remediation runner to distinguish a requested linked-branch revision from
ordinary `in_progress` work without inferring intent from rendered text.

## Projection And Decision Services

Update the GitHub and GitLab review projection services to accept the bounded
review artifact in addition to classification and note references. Their shared
projection decision must:

1. locate exactly one authoritative work item through its persisted linked
   change-request reference;
2. persist review evidence for every classification;
3. move only `findings_present` linked remediation work to
   `review_feedback_required`; and
4. preserve linked, terminal, and provider ownership boundaries.

Add a provider-neutral review-feedback decision service alongside recovery
decisions. It accepts an authorized `requeue` request only for
`review_feedback_required` work with actionable projected feedback. It records
the request and returns `review_revision_queued`. It must reject unsupported
actions, stale command references, absent feedback, and incorrect states.

Existing blocked-work recovery remains separate. It continues to own
publication retry, fresh attempts, and dismissal. A linked open PR/MR with
review feedback is never cleared or routed through `start_fresh`.

## Provider Revision Adapters

Add provider-local revision preparation behind a small provider-neutral
contract returning the current change-request state and source branch. Before
claiming or executing queued work, each adapter must verify:

- the linked request is open;
- its number and URL match the persisted link;
- its head SHA equals `projected_review.reviewed_sha`; and
- its source branch is non-empty and safe for Git operations.

The GitHub/GitLab remediation intake services select queued revision work
separately from unlinked approved work. They claim it atomically through the
existing provider upsert boundary and pass an explicit revision execution
target to the shared runner.

The branch manager gains a narrow existing-branch checkout operation. It must
fetch the named remote branch, verify its head SHA before editing, checkout a
local tracking branch without force-resetting remote history, and use a normal
fast-forward push. A changed remote head, checkout failure, or non-fast-forward
push is a stale revision failure, not a branch-reuse fallback.

`ExecutionService` receives an explicit revision mode rather than overloading
the deprecated dashboard branch parameter. Revision mode reuses the same
analysis, structured-edit, patch, one-file validation, rollback, commit, and
publication logic. Publication verifies and updates the existing PR/MR; it does
not search for or create another request.

## Lifecycle And Rendering

Update shared lifecycle reconciliation so an open linked change request retains
`review_feedback_required` and `review_revision_queued`. It may still refresh
the persisted change-request reference. Merged and closed-unmerged outcomes
continue through the existing reconciliation service.

GitHub and GitLab renderers add:

- a clear review-feedback status label and explanation;
- the existing review projection with bounded findings;
- a requeue instruction only for `review_feedback_required`; and
- queued-revision and last-execution evidence without exposing raw prompts,
  validation output, credentials, or branch commands.

Operational summaries count both feedback statuses as active remediation work.
Finding sync and capacity planning preserve them as protected linked work.

## Failure Behavior

All provider projection, lookup, checkout, and push failures are bounded and
logged. They must not create a second PR/MR, clear the existing link, or alter
the reviewed branch. Failed revisions restore workspace state through the
existing execution safeguards and project the item back to
`review_feedback_required` with compact execution evidence.

## Implementation Slices

1. Add shared state, projected feedback packet, renderer/parser support, and
   review-projection tests.
2. Add shared feedback decision logic and GitHub/GitLab authorized command
   adapters.
3. Add verified existing-branch revision execution, provider-local request
   lookup, and publication reuse.
4. Update lifecycle, capacity/summary integration, runbook guidance, and live
   GitHub/GitLab validation.

## Test Boundaries

- Shared tests cover classification-to-state decisions, feedback bounds,
  command staleness, and unsupported actions.
- GitHub and GitLab parity tests cover authorization, rendering, labels,
  head-SHA validation, branch changes, closed requests, and no duplicate
  change-request creation.
- Execution tests cover one-file scope, validation feedback, rollback,
  fast-forward push rejection, and successful same-branch revision.
- Lifecycle tests cover preserving feedback statuses while open and retaining
  existing merged/closed-unmerged behavior.
