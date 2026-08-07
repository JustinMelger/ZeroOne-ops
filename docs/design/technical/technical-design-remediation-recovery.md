# Remediation Recovery Technical Design

## 1. Scope

Implement the functional recovery contract in
[functional-design-remediation-recovery.md](../functional/functional-design-remediation-recovery.md).

The shared domain owns recovery validation and decisions. Provider adapters own
comment intake, authorization, state storage, and rendering.

## 2. Shared Domain

Add a small recovery package under `services/remediation/recovery/`:

```text
services/remediation/recovery/
  recovery_action_service.py
  recovery_decision_service.py
  recovery_models.py
```

Suggested models:

- `RecoveryAction`: `dismiss`, `requeue`
- `RecoveryRequest`: action, actor, request reference, reason, expected state
  fingerprint
- `RecoveryDecision`: accepted/rejected, resulting state, message, and an
  internal publication-retry or fresh-attempt plan
- `RecoveryEvent`: bounded durable audit entry
- `RecoveryAttempt`: current attempt number and optional prior-attempt link
- `WorkItemResolution`: optional terminal outcome such as `merged` or
  `no_change_required`

The shared decision service must accept a provider-neutral work-item view. It
must not import GitLab or GitHub clients.

## 3. State Changes

Extend the shared work-item model with:

- `attempt_number: int = 1`
- `recovery_events: list[RecoveryEvent] = []`
- `resolution: WorkItemResolution | None = None`

For GitLab, add equivalent fields to the dashboard item model and persisted
machine payload. For GitHub, add them to the work-item issue machine state.

An event is append-only and capped at ten entries during rendering/upsert. The
active `linked_change_request`, `publication_retry`, and `execution_failure`
fields describe the current attempt. Historical values belong in recovery
events.

`dismissed` is also a durable source-identity suppression state. Source sync
must treat it differently from `completed`: a still-active finding with an
identical source identity must not create a new remediation item.

## 4. Preconditions And Decisions

`RecoveryDecisionService.decide(...)` should perform this order:

1. Verify work-item kind and current status.
2. Verify the request fingerprint against the authoritative item snapshot.
3. Apply authorization before invoking shared decisions.
4. For `dismiss`, allow a blocked remediation item and return `dismissed`.
5. For `requeue`, select publication retry only when `publication_retry`, no
   active linked change request, and a recorded branch/commit pair are present.
6. Otherwise, select a fresh attempt when policy eligibility permits it.
7. Append a recovery event to every accepted state transition.

Recovery does not perform source discovery. Fresh attempts use the normal
remediation path, which can complete the item with `no_change_required` only
when its bounded current-workspace analysis proves no patch is needed. It must
otherwise return the existing manual or blocked outcome rather than infer that
the source finding disappeared.

The recovery command adapter owns only authorization, command parsing, and the
authoritative transition back to `approved`. It must not compose execution or
publication dependencies. The normal remediation runner is the single owner of
claiming approved work, selecting the recorded publication-retry path or fresh
execution path, and projecting the final outcome.

## 5. Publication Retry

Publication retry is first queued as `approved` by recovery command handling.
The normal remediation runner claims it, then bypasses `ExecutionService` after
intake:

1. Verify the recorded branch exists remotely at the recorded commit.
2. Search for an open change request for that branch and target branch.
3. Reuse it when present; otherwise create one.
4. Persist the link and clear `publication_retry` only after success.
5. On failure, retain the recorded retry state and return the item to
   `blocked`.

No patch generation, validation command, commit, or branch push occurs in this
path. This is the only safe branch-reuse behavior in v1.

## 6. Fresh Attempts And Branches

`start_fresh` increments `attempt_number`. The branch builder receives this
number and appends a bounded, readable attempt segment such as `attempt-2`.

The existing source-based identity remains part of the name, but attempt
identity prevents non-fast-forward reuse of a branch created by a prior failed
or closed attempt. Compatibility lookup may still recognize existing open
change requests for the current attempt only.

## 7. Provider Adapters

### 7.1 GitHub

Add provider-local recovery comment intake under
`services/control_plane/work_items/`. It should:

1. list comments for the authoritative work-item issue;
2. authorize authors through the existing admin permission service;
3. parse the GitHub command form;
4. load the work-item machine state;
5. invoke the shared decision service;
6. upsert the state and refresh the optional operational summary.

The workflow trigger remains an `issue_comment` event filtered to work-item
issues. The dedicated policy issue continues to process only policy commands.
The derived operational summary must never process policy or recovery commands.

When lifecycle reconciliation closes a dismissed native issue, its
`zeroone-status:dismissed` label and machine state form a bounded tombstone.
Finding sync must search closed dismissed work-item issues by that label and
stable source identity before creating a new open item. It must preserve the
suppression rather than reopening or duplicating the issue. Completed items do
not use this suppression behavior.

### 7.2 GitLab

Add a dashboard recovery-note adapter beside dashboard policy processing. It
should:

1. load dashboard notes;
2. authorize authors through `GitLabPolicyNoteAuthorizationService`;
3. parse an item-targeted command;
4. load the dashboard item; and
5. invoke the shared decision service before persisting the dashboard.

Recovery processing is separate from severity and issue-class policy replay.
It may share comment transport and authorization, but must not extend the
policy state model. Dashboard policy commands remain dashboard-scoped; an
item-targeted recovery command is the only remediation command accepted there.

## 8. Rendering

GitLab rows and GitHub work-item issues should show only the latest recovery
summary in the human-facing view:

- latest action;
- current attempt number;
- current recovery eligibility or blocker;
- link/reference to the previous change request when applicable.

Blocked remediation items additionally render a compact recovery instruction
block containing the current blocker plus provider-local `requeue` and `dismiss`
commands. The renderer owns this text; command processing must not depend on
human-facing Markdown. Non-blocked items do not render recovery instructions.

The bounded event history stays in the machine-managed state block. This keeps
operator views scannable while retaining durable provenance.

## 9. Implementation Slices

### Phase 7a: Shared Contract

- add shared recovery models and decision service;
- add decision tests for every action and invalid precondition;
- extend state parsing/rendering without provider command wiring.

### Phase 7b: Retry Decision And Publication

- add recorded-branch verification and provider-neutral retry decision and
  publish service;
- add GitHub and GitLab adapters for branch and change-request checks;
- cover successful reuse, missing branch, changed commit, and publish failure.

### Phase 7c: Provider Command Surfaces

- add GitHub work-item comment processing and admin authorization tests;
- add GitLab dashboard-note processing and Maintainer/Owner authorization tests;
- expose provider-native workflow triggers and command references.
- ensure source sync preserves GitLab dismissed states and recognizes GitHub
  dismissed tombstones by stable source identity.

### Phase 7d: Fresh Attempt Plan

- add attempt-aware branch naming and fresh-attempt state reset;
- add a bounded `no_change_required` analysis outcome, accepted only when the
  current workspace evidence shows the selected target needs no patch;
- ensure previous branches/change requests remain historical;
- live-test one closed-unmerged item and one failed publication on each provider.

## 10. Deferred Work

- atomic compare-and-set claims;
- automatic retry after transient provider failures;
- cross-repository recovery policy;
- a database-backed recovery history;
- recovery actions for multi-file remediation.
