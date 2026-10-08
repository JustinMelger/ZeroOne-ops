# ZeroOne Ops Work-Item State Projection Technical Design

## Scope

This design introduces a narrow state-projection boundary for GitHub and
GitLab work-item issues. The first consumer is policy reconciliation and its
reversible `policy_deferred` status.

## Design

Keep the canonical model provider-neutral and keep provider transport local.

```text
finding sync / recovery / lifecycle
    -> next WorkItemState
    -> shared state policy
    -> provider-local work-item projection
    -> GitHub or GitLab issue API
```

The shared state policy is pure and owns only the mapping from
`WorkItemStatus` to the desired provider issue state:

```text
candidate, approved, in_progress, blocked -> open
completed, dismissed, policy_deferred, capacity_deferred -> closed
```

It does not import provider clients or interpret labels.

Provider-local projection extends the existing `GitHubWorkItemService` and
`GitLabWorkItemService` composition. The corresponding upsert services remain
the owner of renderer use, label projection, identity checks, create/update,
close, and the new reopen operation. No generic provider protocol or service
locator is introduced.

## Authoritative State Merge

Both provider upsert services delegate parsed state merging to the pure
`merge_authoritative_work_item_state(existing, incoming)` function. Provider
wrappers retain native issue parsing, lookup, rendering, and transport. If the
wrapper cannot parse existing state, it retains its incoming-state fallback.
Direct `update_existing_work_item` operations continue to project the supplied
state without this omission-preserving merge.

The merge keeps the existing work-item ID and preserves only the established
fields when omitted from the incoming model: linked change request, projected
review, publication retry, execution failure, policy/capacity deferral,
resolution, last revision command, review-action timestamp, attempt number, and
recovery history. Explicit values, including `None` and empty lists, take
precedence. Status and all other fields follow the incoming state; claim, queued
revision request, and semantic-safety evidence are not added to the preservation
contract by this extraction. Neither input is mutated.

GitHub retains its existing supplied-field metadata for omitted, empty
`last_revision_command` and `review_action_required_at`; GitLab keeps these
fields omitted. This adjustment remains in the GitHub wrapper. Unchanged
detection also stays provider-local: GitHub compares title and body, while
GitLab additionally compares labels. Dismissal rechecks, identity ambiguity
handling, and provider write ordering retain their existing behavior.

Finding-sync outcomes use a shared frozen `FindingSyncResult` dataclass in the
model layer, with the existing fields, ordering, and defaults. The old
`GitHubFindingSyncResult` and `GitLabFindingSyncResult` imports remain aliases.
This result reports decisions and counters; it does not own reconciliation or
provider projection.

## Shared Finding-Sync Composition

Both issue-mode sync services delegate to `FindingSyncCoordinator`. The
coordinator consumes frozen `FindingSyncRecord` snapshots and a
`FindingSyncInventory` through a narrow `FindingSyncStorage` protocol. It owns
identity indexing and ambiguity handling, policy/capacity decision sequencing,
state construction, guarded projection ordering, stale reconciliation, and
aggregate `FindingSyncResult` counters. The protocol is specific to finding
sync, not a generic control-plane provider abstraction.

Provider-local adapters retain transport, repository/project argument mapping,
native lookup snapshots, and actual persistence responses. Each normalized
record retains its exact native snapshot, even after a later authoritative
re-read of the same issue. Upsert still delegates the native dismissal inventory
to the provider facade, preserving its final dismissal recheck and unchanged
detection behavior. The coordinator receives the provider's logger and display
label so warning wording and logger ownership remain compatible.

The execution sequence remains: load open, closed policy-deferred, closed
capacity-deferred, and closed dismissed inventories once; calculate projected
capacity; process reported findings; then reconcile missing managed-source
records. Capacity planning accounts for safe stale transitions before those
writes occur. An open defer/completion transition re-reads authoritative state,
updates machine state, then closes; reactivation reopens before the active
state update. These operations are not atomic.

Dry runs retain the same inventory reads and selection, with no writes or
transition-counter simulation beyond existing behavior. Existing exception
boundaries are preserved: initial inventory reads, guarded re-reads, ordinary
promotion writes, and legacy demotion writes propagate failures; the existing
defer/reactivation/completion projection blocks log caught failures and retain
their current aggregate counts. In particular, an open capacity-deferral
projection failure logs a warning without incrementing
`projection_warning_count`; this extraction does not change that reporting
limitation or add automatic closure retries.

The coordinator does not execute remediation, interpret review commands, or
reconcile linked PR/MR terminal outcomes. Legacy GitLab dashboard routing and
intake remain outside this composition.

## Policy Reconciliation Flow

1. Finding sync loads all open authoritative work items once.
2. It also loads closed policy-deferred work items once, using both labels:
   `zeroone-work-item` and `zeroone-status:policy_deferred`.
3. Both inventories are parsed and verified before identity matching.
4. Before policy evaluation, a complete managed inventory resolves an absent
   exact identity as `completed/no_longer_detected` when the work item is
   unlinked `candidate` or `approved`, or already deferred. Linked,
   `in_progress`, blocked, and dismissed work remains protected.
5. Policy evaluation then runs before promotion capacity for findings still in
   the inventory. For a policy-ineligible unlinked `candidate` or `approved`
   item, finding sync constructs the next canonical state with status
   `policy_deferred` and passes it to provider-local projection.
6. For a matching closed `policy_deferred` item that becomes eligible, finding
   sync chooses `approved` or `candidate` using the existing capacity plan and
   passes that next state to projection.
7. Incomplete, unavailable, or non-authoritative inventories never infer
   absence and leave existing work unchanged.
8. Provider-local projection updates renderer-owned state and labels, then
   ensures the provider issue is open or closed according to the shared state
   policy.

## Capacity Queue Projection (Locked Follow-Up)

Capacity projection uses a closed `capacity_deferred` state so open issues
represent only work that can progress. Newly observed findings outside the
budget remain non-durable aggregate backlog-only work; no provider issue is
created for them.

Finding sync will load the narrow closed inventory indexed by
`zeroone-work-item` and `zeroone-status:capacity_deferred` alongside the open
authoritative inventory. It will construct one provider-neutral candidate set
from new eligible findings, eligible active candidates during transition, and
matching closed `capacity_deferred` records.

The shared capacity planner owns selection:

- open `approved` and `in_progress` remediation items consume capacity and are
  preserved;
- blocked, dismissed, terminal, and policy-deferred items do not consume it;
- remaining eligible work is ordered by normalized severity (`high`, `medium`,
  `low`) and then stable finding identity;
- only records selected for available capacity project as open `approved` work;
- existing durable candidates outside capacity project as closed
  `capacity_deferred` work;
- newly observed findings outside capacity remain aggregate backlog-only work.

This is a state-projection change, not a source-adapter rule. It applies
identically to GitHub and GitLab issue mode. More refined aging, source
balancing, and operator-set priority are intentionally out of scope.

Before step 5, finding sync re-reads the exact open work-item identity and
verifies it remains unlinked with status `candidate` or `approved`. If the
current state differs, it skips the transition and records it as protected.
This prevents a stale finding-sync snapshot from overwriting a recent
remediation claim or lifecycle update. CI scheduling and provider resource
groups must not be treated as correctness guarantees.

The closed deferred inventory is loaded once per sync and indexed by canonical
identity. The implementation must not issue one closed-issue scan per finding
and must never scan all closed repository issues.

SARIF and other CI artifacts are ephemeral. Collection metadata must include a
source in `managed_source_ids` only after a valid complete collection. A
missing, unreadable, or scanner-failed artifact must produce unavailable-source
diagnostics without managed-source ownership. Workflow templates must not
convert a scanner crash into a valid empty artifact; only a valid complete
zero-result artifact is an authoritative empty inventory.

Policy-comment processing only updates authoritative policy state. It does not
enumerate, update, or close work-item issues. The next successful finding sync
is the sole bounded reconciliation point for policy-deferred transitions.

## Projection Semantics

Add explicit provider-client support for reopening a work-item issue. The
projector should be idempotent:

- active desired state plus open issue: update only if rendered state changed;
- deferred desired state plus closed issue: no provider-state change;
- active desired state plus closed deferred issue: reopen, then render active
  state and labels;
- deferred desired state plus open issue: render deferred state and labels,
  then close.

Provider APIs cannot make all rendered fields and issue state transactional.
Projection errors are logged with work-item identity, provider issue reference,
desired status, and operation. A later lifecycle/status reconciliation may
repair the mismatch. The current finding sync outcome remains authoritative
about inventory and policy, but must expose a projection warning rather than
claim full provider convergence.

The read-before-write guard reduces stale overwrites but is not an atomic
compare-and-set. Provider-bound conditional transitions and atomic claims are a
post-v1 concurrency-hardening track.

Status reconciliation must inspect both inventories required for repair:

- all open authoritative work items, queried by `zeroone-work-item`;
- closed policy-deferred work items, queried by `zeroone-work-item` and
  `zeroone-status:policy_deferred`.

It must not scan all closed provider issues. The reconciliation logic compares
the parsed canonical status with the provider issue open/closed state and uses
the same provider-local projection operation to repair a mismatch.

## Model And Rendering Changes

- Add `policy_deferred` to `WorkItemStatus`.
- Add bounded policy-deferment evidence to `WorkItemState`: reason, occurred
  time, and run ID.
- Add `no_longer_detected` to `WorkItemResolution` for findings absent from a
  complete managed source inventory. It is distinct from remediation success
  and from `no_change_required`.
- Render any terminal resolution in the provider issue's `Status` section with
  an operator-facing label while retaining the canonical value in machine state.
- Add `zeroone-status:policy_deferred` through the existing derived label
  vocabulary.
- Add `capacity_deferred` and its derived status label in the follow-up capacity
  projection slice.
- Add provider-parity rendering for a `Deferred by Policy` section.
- Extend operational summary counts to distinguish policy-deferred work only
  as an aggregate, not as an active open-work count.

## Compatibility And Boundaries

- Until the follow-up capacity projection ships, existing `candidate` remains
  the compatibility state for policy-eligible capacity deferral.
- Existing dismissed tombstone suppression remains unchanged and continues to
  use the narrow closed dismissed-label lookup.
- Policy-deferred transitions are allowed only from unlinked `candidate` and
  `approved` work. `in_progress`, `blocked`, dismissed, and linked work remain
  lifecycle- or operator-owned and are retained unchanged.
- Legacy GitLab dashboard mode remains out of scope.
- Lifecycle retains change-request reconciliation ownership. It may repair
  projection mismatches but does not evaluate finding policy.
- A later remediation review-feedback state may reuse the shared status-to-
  issue-state mapping. Its transition rules, linked change-request handling,
  and revision workflow remain a separate design.

## Tests

- Pure status-to-provider-state mapping, including `policy_deferred`.
- GitHub and GitLab projection transitions: open-to-deferred close and
  deferred-to-active reopen.
- One closed deferred inventory query per finding-sync pass, with no broad
  closed-issue query.
- Protected `in_progress`, `blocked`, dismissed, and linked work is retained.
- Re-enabled work retains its issue, identity, and history.
- Provider projection failures are bounded and do not claim remediation or
  finding resolution.
