# Technical Design: Promotion-Time File/Rule Batching

## Status And Ownership

**Slice 4 activates shared batch sync and execution; live rollout remains an unchecked release gate.**
This document specifies the
[functional batching contract](../functional/functional-design-remediation-batching.md).
Implemented contracts and their ownership are described below. Live provider
validation and release-candidate acceptance are separate from automated completion.
Production activation and release placement remain separate decisions. The
[file-grouping design](technical-design-finding-file-grouping.md) is optional
background, not an ingestion prerequisite.

### Slice 1 Foundation

The optional batch models, strict `max_findings_per_work_item` configuration,
explicit UUID identity factory, pure ownership predicates, and standalone
`FindingBatchPromotionService` are implemented. The shared batch-capable coordinator now serves production
finding sync; historical single-finding work stays independent.

The planner accepts normalized `FindingSyncRecord` snapshots, returns ID-less
`FindingBatchPromotionUnit` proposals and existing selections, per-finding
decision reasons, bounded conflict references, and an active-work count. Models
live in the model layer; category normalization and policy/ownership decisions
remain services. It does not refresh observations, infer absence, allocate IDs,
read clocks, log, or access providers. Existing same-group single-finding
candidates retain separate eligibility/capacity; they are never consolidated.
For reported members, supplied current finding evidence takes precedence over
stored observations for policy evaluation and severity ranking, without mutating
either input. Ownership conflict detection checks durable work-item/source
identities independently of member overlap or grouping keys.

Refreshed evidence for a frozen member must still match the batch's source,
file, and rule scope. A mismatch withholds the entire existing selection without
releasing ownership or silently dropping the mismatched member. Eligible reported
members receive `batch_scope_mismatch`; individual policy and dismissal reasons
remain authoritative. Evidence under a different source ID is a separate identity,
not a refresh of the original member.

After individual policy and dismissal filtering, existing multi-member executable
scopes must meet the same normalized category and requirement compatibility
contract as new batches. Incompatibility withholds the whole existing selection
with `batch_requirements_mismatch`, preserving membership and ownership. Absent,
policy-excluded, and dismissed members do not participate in this comparison.
The shared coordinator persists bounded selection evidence and projects
otherwise selectable mismatched work as blocked, with a shared operator view.

### Shared Sync And Projection

`FindingSyncCoordinator` is the single production composition for both providers;
the transitional internal coordinator and old single-only orchestration are removed.
Public provider service names and result aliases remain stable. Configuration
passes the batch-size limit directly. Shared intake admits typed batches and
loads authoritative policy read-only once when fresh selection needs it; failure
withholds fresh batches without inventing policy. Recorded publication retries
and revisions retain their original scope and do not require a fresh policy load.

The coordinator sequences focused components rather than owning their internals:
`FindingBatchReconciliationService` makes pure observation, eligibility, and
capacity decisions; `BatchFindingCreationService` owns creation authorization and
uncertain-write rediscovery; `BatchFindingSyncProjection` owns guarded provider
projection; and `BatchFindingSyncReport` owns aggregate reporting. Internal typed
run context and creation/projection outcomes live in the model layer, not the
persisted state schema. Helpers return evidence and bounded warnings without
mutating caller counters or logging; the coordinator owns workflow logging.

Capacity-releasing transitions are projected before selection. The coordinator
replans from confirmed persistence outcomes, retaining the original active
reservation when a release fails or is uncertain, including updates that succeed
before closure fails. It does not retry those records in the same sync. Successful
projections carry the returned authoritative state; dry runs simulate successful
releases without writes. This sequencing protects sequential failure accounting,
not concurrent capacity reservations or atomic uniqueness.

Reporting excludes findings owned by capacity-active work from backlog, even if
current policy excludes that protected work. Existing active work is not a new
promotion. Deferred, suppressed, conflicting, overflow, and failed selections
retain finding-unit backlog reasons; inventory totals still come from normalized
findings, independently of promotions and backlog.

GitHub/GitLab storage adapters own strict indexed discovery, exact native-state
reads, identity rediscovery, and issue transport. Their existing live inventory
methods are unchanged. Batch discovery adds only closed nonterminal status
indexes, not general closed history; malformed indexed authority fails closed.
Both adapters compose `FindingSyncRecordStore` for exact native-snapshot retention
and successful open/closed projection tracking. Native issue conversion and API
argument differences remain provider-local; the store performs no provider reads
or workflow decisions.
`FindingSyncProjection` shares update-before-close operations with current sync,
and implements reopen-before-active-update and persist-blocked-before-reopen
ordering without making policy decisions.

Observation refresh reconstructs validated immutable state. Complete managed
inventories may establish absence; unavailable inventories retain last confirmed
presence and mark freshness unknown. Out-of-scope evidence is not stored as a
valid snapshot. Blocked/linked/claimed/review-feedback work receives observation
updates without changing its execution-owned state. Safely manually closed
unstarted batches remain untouched history and are rechecked before replacement.
Observation-only updates preserve native issue closure for protected approved
work. Activation reopens an issue only on a transition into approved, not because
an already-approved record received refreshed evidence. Linked request terminal
outcomes remain lifecycle-owned.

Optional `WorkItemBatch.selection_failure` holds a mismatch reason, run/time,
at most ten unique original member IDs, and an omitted count, never raw constraints
or execution output. Safe selectable failures become blocked, clear deferral
evidence, and render a bounded shared **Selection** section. They remain blocked
until explicit recovery; execution/requeue performs fresh scope reassessment.

### Execution And Recovery

Production single-finding prompts and the `IssueAnalysis` response schema remain
unchanged. Typed batch targets select dedicated analysis/edit templates
and the separate `BatchIssueAnalysis` schema.
Only analysis requests produce member accounting. Edit requests consume accepted
accounting and permit independent minimal same-rule corrections within the one
original file; they do not request analysis fields in the edit response.
Batch review prompts now receive bounded member/attempt evidence exclusively
through uniquely verified work-item linkage. Description text never establishes
authority. The packet is untrusted and instructs review to compare claims with
the diff; ordinary single-finding prompts and schemas stay unchanged.

`BatchExecutionScopeService` resolves original detected members through shared
per-member policy and requirement checks. It retains detected-but-stale evidence,
excludes confirmed absence, and never expands frozen membership. Intake persists
`BatchAttemptEvidence` with the claim, including immutable member snapshots and
observation-run references. Optional analysis coverage must exactly partition
targeted identities; unaddressable/manual members and semantic-safety rejection
block the entire batch rather than dismissing its other members.

Rejected analysis preserves a separate optional `batch_rejection` packet on
`WorkItemExecutionFailure`, not on accepted coverage. It identifies missing or
invalid accounting, unaddressable members, or manual classification. Retain at
most ten affected member display references (300 characters each), bounded
reasons (600 characters each), and an omitted count. References truncated for
display are never used for identity, policy, or execution decisions. Both issue
providers render this packet under **Last Execution** with escaped text. Fresh
recovery clears the current failure through existing transitions; history may
retain the prior rejection. No partial edit or publication is authorized.

Shared presentation derives a bounded failure view from that existing packet,
without schema or execution changes. Exact, unambiguous attempt-member matches
provide recorded file/rule/line locations; unresolved or truncated references
show shared scope with no inferred line. A current blocked analysis rejection,
or failed revision correlated by command timestamp and reviewed SHA, receives a
**Latest Attempt** notice near **Next Action** (three 300-character excerpts).
**Last Execution** shows the ten bounded explanations and collapsed technical
references. Both surfaces disclose omissions and escape external evidence.
Retained assessment evidence is labelled **Retained Change Rationale**, without
inventing run/publication provenance. CLI summaries reuse the category and
bounded explanation view and already-known issue/request URLs; no extra provider
reads or exit-code changes are introduced. Rendering never changes authority.

Batch context uses one enclosing excerpt or the full file. Missing locations
require full-file context; invalid locations or spans outside the existing file
byte/line budget stop before model calls. Large-file excerpts retain the existing
`context_lines_before + context_lines_after + 1` line budget and `max_file_bytes`
byte ceiling. Required members are never silently truncated or clamped.
For same-request revisions, published member locations are historical: if those
lines were removed by the initial fix, full-file context is allowed within the
existing byte limit. The member mandate is retained; no location is silently
rewritten, and no large-file historical-location fallback bypasses the bounds.

Validation retries retain accounting and semantic-safety evidence. Publication
results carry recorded retry state into execution failure projection so a later
blocked-state write cannot erase it. Publication retry and review revisions use
the committed attempt, not new observations. Only authorized fresh recovery can
complete current all-absent work without an edit. Review obtains attempt evidence
through unique persisted linkage, never description parsing.

Absence-driven execution completion uses a narrow existing-issue update rather
than a create-capable upsert. The provider's single authoritative lookup supplies
the latest state to the shared completion guard. All members must still be
confirmed absent with current freshness; identity, membership, attempt, status,
claim, and absence of linked/retry/revision work must still permit completion.
No additional provider read is introduced. Missing or closed authority is not
recreated. Refusal performs no write; a failed projection is unconfirmed and
triggers no follow-up overwrite of authority. Both return an explicit non-completed
result; the runner records a failed control-plane
update rather than claiming absence completion. It does not overwrite newer work
with a blocked-state projection. Existing lifecycle/status handling of claims
remains unchanged. Dry runs report a preview requiring live revalidation, never
durable completion. The race after this read remains outside the v1 guarantee.

Shared state reconstruction and omission-preserving merges retain batch and
attempt evidence. Internal intake indexes the supplied complete open inventory
before ranking: conflicting batch group/member owners are withheld without a
claim, while unrelated work remains selectable. This includes reopened old batches;
the check adds no provider reads and is not an atomic reservation.

`RemediationIntakePreparationService` owns scope preparation and returns a typed
blocking decision; the coordinator owns clocks, claims, and persistence. Invalid
queued revisions keep their revision route so failure returns to review feedback.
At the provider's authoritative upsert read, execution uses
`merge_remediation_work_item_state`: the persisted `batch` (frozen membership,
observations, and selection evidence) remains sync-owned, while `batch_attempt`
is execution-owned. Attempt evidence is revalidated against persisted membership.
Finding-sync writes retain the normal explicit replacement merge; this is not a
global rule preventing observation updates. The read-before-write race remains
until atomic provider transitions are introduced.

Minimal request descriptions enumerate targeted identities and
retain validation/safety evidence without claiming scanner-verified fixes.
Production sync and intake use this shared execution path; slice 4 adds
full issue/summary UX, provider body-size safeguards, and live validation.

Immediately before each create, refresh ownership and exact dismissal inventory
and re-plan the proposed unit without shrinking it. Allocate identity only after
authorization. An uncertain create is never retried in that run: rediscover its
assigned ID in both native states and verify ownership before reusing a unique
authoritative result. Missing/ambiguous outcomes stop creation with a bounded
warning. These reads do not provide atomic uniqueness.

Result transitions count work items; selected-member, unknown-freshness, and
backlog counts use findings. Dry runs read the same authority and simulate
transitions without allocating identities or persistence timestamps. New result
counters default to zero for existing callers. Authoritative state merge retains
omitted batch state but honors explicit replacement or clearing.

Batch-owned evidence uses immutable `BatchFindingSnapshot` models, including
frozen remediation requirements and recursively immutable provenance. The JSON
shape remains the normalized finding shape; shared `NormalizedFinding` models
remain mutable. Existing policy interfaces receive isolated mutable copies via
`to_finding()`. Observation refresh constructs and validates replacement evidence
and batch state instead of mutating stored snapshots in place.

Extend `FindingSyncCoordinator`, its workflow-specific `FindingSyncStorage`
adapters, and the shared execution path. Do not add provider-specific batching
loops. Current identity, capacity, execution adapters, and context contracts
assume one finding; a batch cannot be an arbitrary representative finding with
a different title.

```mermaid
flowchart TD
    A[Source adapters: individual normalized findings] --> B[Shared policy and dismissal filtering]
    P[Provider adapters: authoritative work inventory] --> B
    B --> C[Shared batch planner: ownership, grouping, ranking, capacity]
    C --> D[Provider adapters: recheck and create or reuse issue]
    D --> E[Shared intake: claim one work item]
    E --> F[Shared execution: member context and analysis coverage]
    F --> G[One-file patch, validation, publication]
    G --> H[Provider: one linked PR or MR]
    H --> I[Lifecycle: request terminal reconciliation]
    A --> J[Shared sync: refresh observations]
    J --> D
```

Finding sync owns observations and safe unstarted projections; remediation owns
execution and outcomes; recovery authorizes retries; lifecycle owns linked-request
terminal state. Providers own discovery, authorization, transport, projection,
and request lookup. Git operations remain in focused Git services. Runner/CLI
composition, individual ingestion, and one-file patch safety remain intact.

## Configuration And State Contracts

Use `remediation.max_findings_per_work_item: int = 10`, strictly positive,
rejecting booleans and non-integer coercion. No new numeric ceiling is introduced;
execution budgets remain hard limits. `1` uses single-finding handling for new
work. Configuration changes never resize existing batches.

Add optional `batch` state to `WorkItemState`, absent by default. Historical
singles continue decoding, rendering, and executing under their current contracts.
Never infer membership from titles or descriptions. Illustrative interfaces:

```python
class FindingBatchGroup(BaseModel):
    repository_scope: str
    file_path: str
    source_id: str
    rule_id: str


class BatchMemberObservation(BaseModel):
    finding_id: str
    last_confirmed_presence: Literal["detected", "absent"]
    freshness: Literal["current", "unknown"]
    sync_run_id: str
    observed_at: datetime
    last_confirmed_sync_run_id: str | None = None
    last_confirmed_finding: BatchFindingSnapshot | None = None


class WorkItemBatch(BaseModel):
    schema_version: Literal[1] = 1
    group: FindingBatchGroup
    members: tuple[BatchFindingSnapshot, ...]
    observations: tuple[BatchMemberObservation, ...]


class BatchUnaddressableMember(BaseModel):
    finding_id: str
    explanation: str = Field(min_length=1, max_length=600)


class BatchAnalysisCoverage(BaseModel):
    addressed_member_ids: list[str]
    unaddressable_members: list[BatchUnaddressableMember]
```

Require nonempty unique members, exactly one observation per member, and shared
source/path/rule matching the group. Preserve full original normalized member
snapshots, including provenance and requirements. Observations refresh evidence
for the same exact identity; they never rewrite or replenish original membership.
Keep only the latest freshness observation and last confirmed presence/evidence
per member, alongside its frozen original snapshot. Initialize promoted members
as detected. A reported detection updates confirmed presence, finding evidence,
and confirmation run. Complete managed inventory absence updates confirmed
presence to absent and advances the confirmation run, retaining the last detected
finding for history. Both confirmations set freshness to current.

An incomplete/unavailable/unmanaged inventory that cannot confirm a member marks
freshness unknown, without changing its confirmed presence, evidence, or
confirmation run. A previously absent member therefore remains outside execution
until a later authoritative detection restores it. Previously detected members
remain subject to normal eligibility and bounded-evidence checks; scanner failure
neither drops them nor restores absent members. Latest sync run/time identify the
freshness assessment, while the confirmation reference identifies its evidence.

Derive policy eligibility from the current policy and last confirmed finding,
falling back to the original snapshot. Derive counts and the executable subset
from those decisions and observations; do not persist parallel eligibility flags,
counts, or a mutable executable-member list on the batch. Mark unknown freshness
explicitly. Persist exact targeted member IDs only as execution-attempt evidence,
where publication retries and review continuity need a historical scope.

The work-item ID is the durable batch ID. Its source reference uses the canonical
source ID and reserved `batch-v1:<uuid>` item key; member finding IDs remain
unchanged. Top-level file, rule, source, severity, and summary describe the batch,
not a representative member. Validate consistency with nested state on parsing.

Example observation projection for a frozen batch, omitting full member objects:

| Original member | Last confirmed presence | Freshness | Policy | Attempt scope |
| --- | --- | --- | --- | --- |
| A | detected | current | eligible | targeted |
| B | absent from complete inventory | current | eligible | excluded as absent |
| C | detected | current | excluded | excluded by policy |

Original count is three, detected two, absent one, policy-excluded one (a subset
of detected), executable one. Persist run/time references for these observations.

## Compatibility, Identity, And Capacity

The grouping key is repository scope, canonical repository-relative path, stable
source ID, and diagnostic rule ID. Do not case-fold paths or infer a rule from
an occurrence ID. Missing grouping evidence retains single-finding handling,
subject to existing eligibility checks.

Normalize category aliases using the existing helper. Compatible requirements
mean equal category, expected change, constraints, validation commands, and
acceptance criteria. Preserve command order and exact text; compare acceptance
criteria as sorted unique strings without rewriting contents. Empty/missing lists
are equivalent; absent and nonempty text are not. Differing signatures within an
eligible unowned group fall back to singles, not semantic requirement merging.
Only one new unit for that group may be selected in a pass.

Shared planning proceeds without writes:

1. Apply individual policy and exact dismissal suppression.
2. Expand batch members and existing single identities into one ownership index;
   ambiguous ownership stops conflicting selection.
3. Preserve active approved/in-progress/review-feedback capacity consumers and
   same-group protected work, including claims, links, and blocked work. Deferred
   durable batches compete as frozen units, not as new member proposals.
4. Sort unowned compatible members by severity then stable source/finding ID;
   take at most the configured limit. Overflow stays non-durable backlog.
5. Rank candidate units by source priority (default `100`), highest currently
   executable severity, canonical group key, then stable member identity. Larger
   units receive no bonus. Count one durable/new unit per capacity slot.
6. Preserve capacity-deferral behavior for durable losers; create no issues for
   unselected new units. A nonterminal batch reserves its group until terminal.

Existing issues are never absorbed, superseded, resized, or closed by batching.
Approved singles retain separate capacity usage; deferred singles retain member
ownership. Existing protected duplicates remain intact but stop conflicting new
promotion. Dismissal suppresses exact original member identities, not the group
forever. Completed batches do not indefinitely own future findings.

Assign a UUID4 once when a new batch is selected for creation. Use its hex value
in the `work-<uuid>` work-item ID and `batch-v1:<uuid>` source item key. Retain
that ID across retries of the same creation operation; once persisted, reuse
the provider's authoritative ID and membership. Observation changes, recovery,
and review revisions never generate a replacement ID for the same work item.

No predecessor field, generation chain, or terminal-history lookup is required
to assign identity. Authoritative group/member ownership, not lineage, controls
whether new work may be created. Multiple nonterminal owners are ambiguity;
preserve existing authority rather than select one arbitrarily.

| Previous same-group work | New batch behavior |
| --- | --- |
| Open candidate/approved work, or executing, claimed, deferred, or review-feedback work | Retain group ownership; no new batch. |
| Manually closed safe unstarted candidate/approved batch | Release ownership without suppression; still-reported eligible findings may be selected again. |
| Blocked, including a request closed without merge | Retain ownership and use existing explicit recovery; no automatic replacement. |
| Completed after merge or as `no_longer_detected` | Release group ownership; a later scan may promote eligible unowned findings. |
| Dismissed | Release group ownership, but suppress its exact members through the existing dismissal inventory. Other eligible members may form a new batch. |

Safe unstarted batch work means unclaimed candidate/approved state with no linked
request or execution, recovery, publication-retry, or review history. Native issue
closure releases only this narrowly defined ownership; it does not manufacture a
terminal machine-state resolution. Protected closed work retains ownership. A
merged request releases its group only after existing lifecycle reconciliation
records completion. Preserve historical single-finding ownership rules and
protected duplicates without migrating them into batches.

## Discovery And Creation Protocol

Retain current open and narrow deferred/dismissed inventories and their complete
pagination. Expand parsed batch members into the shared ownership and suppression
indexes. No general closed-batch history scan is needed for planning or identity.
Incomplete/failed ownership discovery stops affected creation rather than being
treated as an empty inventory.

Add narrow label-filtered closed nonterminal batch discovery to distinguish
manually closed safe unstarted work from protected closed work. Query the existing
candidate/approved/in-progress/blocked/review-feedback status indexes, verifying
parsed state; deferred work is already indexed. Release only safe unstarted
batch ownership and retain protected records in the shared ownership index. Do
not infer protection or suppression from provider closure alone. These reads are
not terminal predecessor-history queries and apply equally in dry runs.
Exclude released manually closed batches from automatic reactivation and intake;
status repair must not reopen them as an alternative to creating new eligible
work. Keep their issue bodies as history without assigning a false completion
or dismissal resolution. Re-read native closure and machine state before acting
on a release decision, just as other ownership changes require rechecks.

Extend the narrow storage boundary with typed group-ownership reads and targeted
batch-ID rediscovery for uncertain writes. Use a derived `zeroone-batch:<uuid>`
label alongside the work-item label for exact-ID lookup across open and closed
issues; verify its parsed machine-state ID and membership. Labels remain indexes,
not proof. Keep native issue snapshots local. Immediately before creation, refresh
open/deferred group ownership and member dismissals, including overlap with
singles. Upsert checks batch identity and member overlap, not just its synthetic
source key. Reuse unique persisted batches without recomputing membership.

```mermaid
sequenceDiagram
    participant S as Shared sync
    participant P as Shared planner
    participant A as Provider adapter
    S->>A: Load open and indexed deferred/dismissed inventory
    S->>P: Findings, policy, ownership, capacity
    P-->>S: Deterministic proposal
    S->>A: Recheck group ownership and member dismissals
    alt Matching authoritative batch
        A-->>S: Reuse persisted ID and frozen members
    else No conflicting authority
        S->>S: Assign one immutable batch ID
        S->>A: Create issue with full machine state and labels
        A-->>S: Actual persisted record
    else Ambiguous ownership or write outcome
        A-->>S: Stop group and warn
    end
```

After an uncertain create response, search the assigned batch ID across issue
states and refresh group/member ownership before any further creation attempt.
Reuse a unique authoritative match, including its actual persisted membership.
If no match establishes the outcome, stop that group for the run rather than
blindly retrying, even after a successful empty search. A subsequent sync must
rediscover current ownership before selecting new work, not simply regenerate
the failed proposal's ID and resend it. Intake also rejects duplicate membership.
Preflight reads and creation are not atomic; concurrent writers can still race.
No provider CAS, reservation, or exactly-once guarantee is claimed.

Reopening an old issue after replacement creation is covered by the shared
ownership check: conflicting same-group work or member overlap excludes ambiguous
new pickup and emits a bounded warning with issue references. Preserve existing
execution and let the operator close the redundant safe unstarted issue. No
reopening-specific workflow, persisted status, or automatic repair is required.
Add one regression scenario proving reopened conflicting work cannot start
another execution and produces the warning.

## Observation Reconciliation And Freshness

Match members by exact source/finding identity within repository scope. Reported
members are detected; absence requires a complete managed inventory for that
source. Incomplete/unavailable/unmanaged inventories cannot establish absence.
They also cannot reverse previously confirmed absence: retain that presence and
mark freshness unknown. Unavailable syncs do not introduce new absence-based
terminal transitions. Only a later reported detection can restore an absent
member to the potential executable scope.
Location movement remains old-absent/new-occurrence, not relocation matching.

For safe unstarted work: all absent takes precedence and completes as
`no_longer_detected`; otherwise no remaining eligible members means policy
deferral; otherwise capacity selects approved or capacity deferred. Re-enable the
same frozen batch, never replace it. Use existing guarded update-before-close
and reopen-before-active-update ordering, authoritative re-reads, and warnings.

Blocked, claimed, linked, and review-feedback states are not safe unstarted work.
Refresh observations while preserving status, claim, failure evidence, review,
and linkage. Even all-absent blocked work remains blocked. After accepted operator
requeue, select the existing recovery mode before reassessing member scope.
Publication retry retains the recorded commit and targeted members; refreshed
absence does not convert it into all-absent completion. Only fresh-attempt
recovery reassesses remaining original members. If all are then confirmed absent
and no linked-request lifecycle takes precedence, complete without a model call
or request. Recovery must permit that authorized reassessment rather than
reject it solely because no promotable finding remains. Existing authorization,
replay, and linked-request rules still apply.

### Existing Scan-Before-Sync Contract

Batching inherits the same pipeline contract as single-finding work: scan the
trusted target branch, consume that pipeline's reports in finding sync, then
run the control plane. A later pipeline scans the updated target branch after
merge before promoting further work. The target-branch setting alone does not
refresh a report or prove which checkout it describes.

SARIF producers must generate the configured reports from that pipeline's scan
checkout and wire those artifacts to sync; do not substitute a cached report
after a failed producer. For SonarQube, the pipeline must wait for its submitted
analysis to finish before collecting findings. Preserve existing scanner failure
and incomplete/unavailable-source behavior; never manufacture empty successful
inventories after failure. These are pipeline installation requirements, not
new runtime provenance checks.

Lifecycle completes merged batches immediately under existing rules. Subsequent
intake may promote overflow or previously excluded members from current reports
without reopening completed batches or bypassing dismissal. No merge checkpoints,
revision-provenance schema, ancestry verification, or freshness-specific backlog
gate is added. Batch IDs require no predecessor links or merged-batch history.

Runtime cannot independently detect every stale report supplied by a misconfigured
pipeline. Document that residual limitation instead of claiming revision-verified
freshness. Stronger provenance enforcement is separate future hardening, not a
batching prerequisite or a scanner-resolution guarantee.

## Execution Contracts And Retry Safety

Extend `RemediationExecutionTarget` and `IssueContext` with typed batch evidence:
batch ID, frozen snapshots, observation references, and exact executable member
IDs. Retain existing single fields for singles, not as batch authority. Snapshot
the executable subset after authoritative claim/recovery checks and persist it
with attempt evidence for publication retry and review continuity.

Use the existing single-snippet context contract: construct one continuous source
excerpt covering every executable member's known location, with normal surrounding
context, or include the full file when it fits existing limits. Include guidance
once. Do not introduce independently selected snippet windows or concatenate
disjoint fragments. Missing member locations require full-file context; if it
cannot fit, block. Existing file/line/character budgets apply across the packet.
Verify that bounded selection has not truncated any required member location;
if complete adequate evidence cannot fit, block before model calls. Unknown
freshness retains last confirmed evidence or the original snapshot; inability to
analyze it safely blocks rather than silently deleting the member. Revision
context still follows verified checkout.

Analysis adds `BatchAnalysisCoverage` to the existing aggregate strategy, intent,
and semantic-safety assessment. Addressable members need only their IDs; bounded
nonblank explanations are required only for unaddressable members. The two lists
must be disjoint and together exactly cover the executable identity set; reject
missing, duplicate, or foreign IDs. Any manual/unaddressable member blocks the
complete batch; do not dismiss its other members through the single-finding manual path.
Batch semantic-safety rejection also blocks. Deterministic validation checks
shape and coverage, not claim correctness or actual diagnostic resolution.

Structured edit receives every accepted member, its requirements, accounting,
and assessment in existing untrusted evidence blocks. Trusted constraints keep
the original file as sole editable scope. A model's inability to locate a member
is not authoritative absence. Multiple edits in that file are permitted under
existing patch, rollback, baseline, validation, and publication safeguards.

```mermaid
sequenceDiagram
    participant I as Shared intake
    participant E as Shared execution
    participant L as Analysis and edit model
    participant V as Patch and validation
    participant A as Provider publication
    I->>E: Claimed batch and executable scope
    E->>E: Guard, branch preparation, complete context coverage
    E->>L: All executable members as untrusted evidence
    L-->>E: Member accounting and semantic-safety claim
    E->>E: Validate coverage and structural gate
    alt Every member addressable
        E->>L: Generate complete one-file edit
        E->>V: Apply and validate
        alt Validation permits publication
            E->>A: Publish one request
        else Patch or validation failure
            E->>E: Roll back and block; publish no subset
        end
    else Missing evidence or unsafe member
        E->>E: Block with bounded member references
    end
```

Validation retries retain attempt scope and assessment. Publication retries use
committed attempt evidence and intent, never select new members. Fresh recovery
may narrow scope from new observations without resizing membership. Resolve
`retry_publication` before applying fresh-attempt all-absent completion. Verify
the recorded branch and commit using existing publication-retry controls; if
verification fails, retain blocked failure evidence rather than silently falling
back to a fresh attempt or claiming completion. Same-request
review revisions retain the published attempt scope and original file, treating
feedback as untrusted evidence. Sync cannot rewrite a linked request's mandate.
Review loads evidence through unique persisted linkage, not description parsing.
Failed revisions retain `review_feedback_required`, not dismissal.

```mermaid
sequenceDiagram
    participant O as Operator
    participant S as Finding sync
    participant R as Recovery
    participant E as Remediation
    S->>S: Refresh observations; retain blocked state and failure
    O->>R: /zeroone remediation requeue on work-item issue
    R->>R: Authorize, check replay, current state, and linkage
    R->>R: Select recovery mode and persist accepted transition
    alt Recorded publication retry
        E->>E: Verify and publish recorded commit with original attempt scope
        Note over E: Verification/publication failure stays blocked; no fresh fallback
    else Fresh attempt
        E->>E: Reassess original members from latest authority
        alt All absent and no linked lifecycle takes precedence
            E->>E: Complete no_longer_detected without edit
        else Remaining eligible members
            E->>E: Attempt complete scope or block with evidence
        end
    end
```

## Projection, Evidence Preservation, And Counters

Extend shared rendering with bounded member details and original/detected/absent/
policy-excluded/unknown/attempt-targeted counts. Tie counts to observation runs;
excluded detected members are a subset, not an additional population. Retain
provider-specific terminology and issue command routing. Descriptions distinguish
targeted findings, confirmed absence, validation, and **Change Rationale** claims.
The last is an operator-facing name for internal semantic-safety evidence, not
independent verification.
Neither publication nor merge is scanner-verified resolution.
Unknown freshness can overlap detected or absent counts; show these as last
confirmed counts with their confirmation references, not a new unknown-presence
population or fresh scan result.

Follow the functional design's task-first layout: concise purpose, status and
state-derived next action, compact counts, and a bounded table of original line,
finding message, and current scope. Keep the title's original member count
stable. Derive planned targeted counts before execution; after publication use
persisted attempt IDs for the change's targeted count. Keep observation-run
references visible so neither count is mistaken for scanner-verified fixes.
Render validation/request/safety evidence below the overview when available;
collapse detailed diagnostics/provenance and machine state. Preserve current
escaping and provider body limits for all messages and paths.

Render the functional contract's concise closing explanation on both providers
alongside existing operator guidance. Compute safe-unstarted versus protected
wording using the same shared predicate as ownership selection. Closing is not
dismissal: explain possible replacement for safe work, and retained ownership for
protected work. Preserve existing command eligibility; never advertise unsupported
dismissal/requeue commands on unstarted issues. This is proposed renderer behavior,
not a change to currently shipped issue bodies.

Never truncate authoritative membership to fit a provider body. If full state
cannot fit, stop promotion with a bounded warning. Keep paths escaped and evidence
untrusted. Existing single issue bodies retain their current rendering.

Audit full-state reconstruction and omission-preserving merges: sync owns
observations, execution/recovery own attempt evidence, lifecycle owns linked-request
terminal outcomes. Preserve other owners' fields explicitly. Extend the tested merge
preservation list where required; do not assume newly added omitted fields are
automatically retained by the current merge helper.

Promotion, capacity, and transition counters use work-item units; backlog and
policy reasons use finding units. Add explicitly named selected-member and
unknown-freshness counts rather than mixing units. Dry runs read the same indexes
and source inventories and calculate the same proposal, with no writes, claims, models,
close/reopen operations, or summary publication.

## Verification And Incremental Delivery

| Test boundary | Required acceptance cases |
| --- | --- |
| Models/planner | Default ten, positive limit, limit one, frozen membership, exact requirements, deterministic source/severity ranking, immutable IDs, terminal versus nonterminal group ownership, twenty-three-to-ten overflow, one slot per unit. |
| Shared sync | Existing singles intact, owned/dismissed members excluded, protected groups, deferred reuse, derived eligibility/counts after policy changes, one/all absent, unavailable inventories, location shifts, blocked observations, authorized all-absent recovery. |
| Observation continuity | Complete scan marks a member absent, later scan failure marks only freshness unknown, member stays excluded; a later authoritative detection restores eligibility. Previously detected members remain detected-but-stale; unavailable sync introduces no new absence-based completion. |
| Pipeline contract | Scan before sync, current-pipeline artifact wiring, Sonar analysis completion before collection, no stale artifact substitution after producer failure, existing unavailable-source behavior, fresh reconsideration without reopening old issues. |
| Provider parity | Existing indexes plus closed nonterminal batch discovery, safe manual closure versus protected closure, exact-ID rediscovery across issue states, duplicates, late ownership/dismissal/closure, uncertain creation with no blind retry, persisted-ID reuse, machine-state round trips, projection order/failure isolation, dry-run zero writes. |
| Execution | One enclosing excerpt or full file, distant locations exceeding budgets, missing locations, no silent truncation, exact disjoint coverage lists, bounded unaddressable reasons, manual member, semantic rejection, rollback, no partial request, persisted attempt scope and intent through retries. |
| Review/lifecycle | Checkout before context, same-request revision, linked protection, one successful request, merge completion, closed-unmerged recovery. |
| Recovery precedence | Publication retry retains recorded commit/scope even after all members become absent; verification failure stays blocked without fresh fallback; fresh recovery alone may complete all-absent work without publication. |
| Rendering/reporting | Task-first layout, stable title count, meaningful member table, planned versus persisted attempt scope, state-derived next action, count units, unknown freshness, bounded escaped evidence, provider body overflow, truthful targeted/absent/merged wording, state-aware closing consequences, only supported commands. |

Delivery remains sequential and reviewable:

1. Add optional typed state, configuration, identity/ownership expansion, and pure
   planner tests without enabling batch publication.
2. Extend provider indexes/storage, sync observations, and projection under the
   existing scan-before-sync contract. Keep batch publication unavailable until
   execution support is complete.
3. Integrate internal context coverage, analysis, one-file execution, evidence
   persistence, recovery/retries, typed review context, and minimal publication evidence.
   Keep production batch creation and intake disabled.
4. Complete operator UX, rollout safeguards, GitHub/GitLab parity, existing-single
   regressions, production prompt/schema activation, batch review guidance, and
   live validation. Document scan-before-sync
   requirements and stale-report limitations.

Implementation must run Ruff, formatting, architecture checks, mypy, Bandit,
and the full suite, followed by workflow boundary review. This documentation-only
slice requires local links, fenced blocks, and whitespace validation. Publishing
the design does not complete an implementation or release-gate checkbox.

## Slice 4 Operator Projection And Payload Budget

A pure shared batch view separates frozen original membership, last-confirmed
presence, freshness, explicit policy evaluation, planned scope and recorded attempt
scope. Renderers perform no lookups or state transitions. With no explicit policy,
policy-dependent counts are not evaluated. Task-first issues use a stable neutral
title bounded to 120 characters, a maximum ten-row member overview and 300-character
message excerpts. Display omissions never truncate machine authority.

A shared application guard checks complete batch issue bodies and PR/MR descriptions
against 60,000 UTF-8 bytes before transport. New oversized proposals return
`projection_size_exceeded`; uncertain-create rediscovery is not used for a known
no-write size failure. Existing oversized updates preserve authority and report
failure. Reopen/claim/publication must not bypass this guard. Dry runs render a
non-persisted size preview without allocating UUIDs or reading a persistence clock.

Reporting distinguishes selected finding members and backlog findings from promoted
work items, capacity consumers and transition counts. Inventory totals derive from
normalized severity counts. Persisted summary observations accept old observations
and add optional batch counters. No deferred-member list is published.

Live GitHub/GitLab batch execution, review/requeue and merge reconciliation remain
operator acceptance gates; automated implementation is not live validation.
