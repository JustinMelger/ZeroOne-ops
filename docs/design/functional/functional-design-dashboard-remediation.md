# AI Code Ops Dashboard Remediation Functional Design

## 1. Purpose

Build a dashboard-backed remediation workflow that:

1. reads one structured work item from the dashboard,
2. selects one remediation-ready item safely,
3. analyzes the local repository against that item,
4. proposes and validates a code change,
5. opens a merge request when the change is acceptable,
6. updates the dashboard item lifecycle as the work progresses.

This document defines the functional behavior for moving remediation from
source-specific intake toward a dashboard-first operating model.

## 2. Goals

- Make the dashboard the shared work queue for remediation-ready items.
- Decouple discovery from code-changing remediation.
- Allow multiple producers to feed one generic remediation workflow.
- Preserve the narrow, safe remediation scope already proven in the SonarQube
  v1 workflow.
- Keep the remediation bot deterministic, traceable, and easy to operate.

## 3. Non-Goals

- Auto-remediating every dashboard item type in the first version.
- Replacing GitLab merge requests as the review surface.
- Letting free-form dashboard text become remediation input.
- Supporting broad refactors or multi-file rewrites in the first dashboard
  remediation version.
- Solving long-term cross-repo queueing, locking, or analytics in the first
  implementation.

## 4. Primary User Story

As a maintainer, I want discovery bots to write structured dashboard items and
the remediation bot to pick up one supported item at a time, so the code-changing
workflow no longer depends directly on SonarQube or another single source.

## 5. Assumptions

- GitLab remains the primary platform in the first implementation.
- The dashboard is a persistent GitLab issue with a strict machine-readable
  format.
- Only some dashboard item types are remediation-ready at first.
- The local repository workspace and validation commands remain the primary
  safety gate before merge request creation.
- Merge requests remain the main human review surface.

## 6. External Systems

- GitLab dashboard issue
  - source of structured work items
  - updated with item lifecycle changes
- GitLab merge requests
  - output surface for code changes
  - durable operational state for opened remediation work
- local repository workspace
  - source analysis, edit rendering, validation, git operations
- LLM provider
  - item analysis and structured edit generation
- upstream discovery producers
  - SonarQube dashboard sync
  - later pipeline-failure discovery
  - later internal review discovery

## 7. High-Level Functional Flow

```mermaid
flowchart TD
    A[Start Remediation Run] --> B[Load Dashboard]
    B --> C[Select One Supported Open Item]
    C --> D{Eligible Item Found?}
    D -- No --> E[Exit With No Work]
    D -- Yes --> F[Mark Item In Progress]
    F --> G[Build Repository Context]
    G --> H[Analyze Item And Generate Structured Edit]
    H --> I[Render Diff And Apply Patch]
    I --> J[Run Validation Commands]
    J --> K{Validation Passes?}
    K -- No --> L[Fail Item And Restore Workspace]
    K -- Yes --> M[Commit And Push Branch]
    M --> N[Create Or Reuse Merge Request]
    N --> O[Update Dashboard Item To MR Opened]
    O --> P[End]
```

## 8. Proposed Logical Components

### 8.1 Dashboard Item Source

Responsible for:

- loading the dashboard issue,
- parsing structured items,
- selecting one eligible remediation item,
- returning a typed work item to the remediation workflow.

### 8.2 Dashboard Item Selector

Responsible for:

- filtering supported item types and statuses,
- skipping items already represented by an active merge request,
- enforcing ordering and fairness rules,
- returning stable skip reasons for observability.

### 8.3 Work Item Analyzer

Responsible for:

- mapping the selected dashboard item into a repository-context request,
- keeping scope bounded to the supported remediation model,
- rejecting items that exceed current remediation capability.

### 8.4 Generic Remediation Workflow

Responsible for:

- taking one structured work item,
- producing a structured edit,
- rendering a bot-owned diff,
- validating and publishing the result.

The shared remediation workflow should consume a remediation-native work-item
contract rather than requiring every producer to masquerade as a SonarQube
issue internally.

That means:

- SonarQube remains one supported producer profile,
- future producers should plug into the same workflow through the shared
  remediation contract,
- source-specific prompt shaping or policy can still exist where needed, but it
  should not redefine the base execution model for every producer.

### 8.5 Dashboard Lifecycle Updater

Responsible for:

- transitioning dashboard item statuses,
- recording merge request links,
- moving failed or rejected items out of active sections,
- keeping the dashboard in sync with remediation progress.

The first implementation should keep this responsibility narrow:

- the remediation workflow owns transitions it can observe directly during its
  active run,
- later reconciliation of merged, closed, or otherwise externally changed merge
  requests should remain a separate maintenance workflow.

## 9. Remediation-Ready Dashboard Item Contract

An item should only be selectable for remediation when it includes:

- `id`
- `source`
- `type`
- `status`
- `title`
- `summary`
- `priority`
- `source_reference`

And, when relevant for code remediation:

- `file`
- `line`
- `validation_commands`
- `expected_change`
- `constraints`
- `acceptance_criteria`

For the first dashboard-backed remediation version, only `constraints` should
be treated as a producer-neutral execution input. The other optional fields can
be preserved on the item as metadata, but they should not yet change runtime
behavior until their enforcement semantics are defined more clearly.

The remediation workflow should reject items that are:

- structurally incomplete,
- outside supported item types,
- already in progress elsewhere,
- too broad for the current remediation scope.

## 10. Initial Supported Item Types

The first dashboard-backed remediation version should stay narrow.

Recommended initial support:

- Sonar-derived single-file code smell items already compatible with the
  current structured-edit workflow

Deferred item classes:

- pipeline-failure-derived test fixes
- complex single-file refactors
- symbol-safe rename issues
- multi-file changes

## 11. Selection Rules

The remediation workflow should select:

- only items with status `open`
- only supported item types
- only items that still satisfy current remediation policy
- only one item per run

The workflow should skip items when:

- a matching merge request is already open,
- the item is not remediation-ready,
- the item exceeds supported scope,
- the item has been marked `ignored` or `rejected`,
- the item is already `in_progress` for another run.

## 12. Item Lifecycle

Recommended lifecycle transitions:

- `open`
  - initial state after discovery or after a previously resolved issue reopens
- `in_progress`
  - selected by remediation and currently being processed
- `mr_opened`
  - remediation succeeded and a merge request exists
- `done`
  - issue no longer active upstream or remediation no longer required
- `rejected`
  - human or policy rejected remediation for this item
- `ignored`
  - explicitly out of scope for current automation
- `failed`
  - remediation attempted but did not complete successfully

The workflow should preserve stable item IDs across transitions.

For the first implementation, the remediation bot should own only the
transitions it can observe directly while it is running:

- `open -> in_progress`
- `in_progress -> mr_opened`
- `in_progress -> failed`
- `in_progress -> rejected`

Later transitions driven by external events, such as a merge request being
merged or closed after the remediation run has ended, should be handled by a
separate reconciliation workflow rather than making the remediation bot a full
long-lived state controller.

## 12.1 Stale In-Progress Recovery

The first implementation should define what happens when a run marks an item
`in_progress` and then does not finish cleanly because the job is canceled, the
runner crashes, or the process loses network access mid-flight.

## 12.2 Merge Request Reconciliation

Before product demonstration, the dashboard workflow should also define how
items leave `mr_opened` after the merge request state changes outside the
active remediation run.

This should be a separate scheduled reconciliation workflow rather than an
extension of the remediation bot itself.

Recommended ownership split:

- the remediation workflow owns active-run transitions only,
- the reconciliation workflow owns later merge-request convergence,
- the stale `in_progress` recovery rule remains owned by remediation intake and
  should not be duplicated by reconciliation.

Recommended reconciliation behavior:

- when the linked merge request is merged, move `mr_opened -> done`
- when the linked merge request is closed without merge and the item still
  represents valid open work, move `mr_opened -> open`
- when the linked merge request is closed without merge and the remediation is
  no longer needed, move `mr_opened -> done`
- when merge-request metadata is missing, inaccessible, or no longer matches
  stored branch and commit traceability well enough to make a safe decision,
  move `mr_opened -> failed` with an explicit operator-facing reason

The reconciliation workflow should be conservative. It should prefer explicit
failure or reopen behavior over silently dropping item history.

The first version should operate on:

- items currently in `mr_opened`
- one dashboard issue at a time
- scheduled or manually triggered CI runs

The first version should not own:

- item selection for remediation
- patch generation or validation
- active-run `in_progress` recovery
- broad dashboard cleanup outside merge-request convergence

At minimum, operators should be able to tell:

- whether the item is still actively being processed,
- whether the item should be moved back to `open`,
- whether the item should be left `in_progress` for manual follow-up.

The workflow should prefer explicit recovery rules over leaving stale
`in_progress` items ambiguous forever.

## 12.3 Failed-Item Recovery Model

The workflow should distinguish between:

- diagnosis state
  - the item failed and the operator still needs to understand why
- recovery-ready state
  - the cause is understood and the next action is clear enough to present as a
    workflow step

`Investigate Failure` should therefore be treated as a diagnosis-oriented
operator state, not as the final answer for what happens next.

The first recovery model should stay narrow and support these broad classes:

- operational failure
  - example: expired token, inaccessible GitLab metadata, missing tool in CI
- validation failure
  - example: tests fail, lint fails, type checks fail
- policy or review block
  - example: retry blocked by latest review outcome
- manual follow-up outcome
  - example: remediation analysis decides manual review is required

The dashboard should later make the likely recovery path clearer for each
class:

- operational failure
  - fix environment or credentials, then rerun the relevant workflow
- validation failure
  - inspect whether the generated patch is wrong or the repo command/tooling is
    misconfigured
- policy or review block
  - leave blocked until the governing policy or review state changes
- manual follow-up outcome
  - route to explicit human follow-up rather than automation retry

The first implementation does not need a full operator command surface yet, but
it should define the state semantics clearly enough that later retry or reset
actions are not invented ad hoc in dashboard rendering.

Large legacy repositories also need bounded presentation behavior. Once the
workflow board is split into clearer buckets, the dashboard should later define
how many items each operator-facing section shows by default and how hidden
overflow is summarized.

Recommended later direction:

- show only the most relevant subset in each workflow bucket
- preserve aggregate counts in the overview so operators still understand total
  backlog size
- make overflow visible through summary text such as "N more items not shown"
  rather than silently truncating the board
- prefer bucket-specific limits after the board structure is clarified instead
  of one global cap across all workflow items

Monorepo scaling should also be investigated later. If one repository contains
multiple distinct applications or domains with large independent backlogs, one
repo-global dashboard may become too noisy even with better buckets and capped
tables.

Later options may include:

- grouping workflow sections by scoped repo area
- path- or component-aware summaries
- or one dashboard issue per configured repo scope instead of one global board

## 12.4 Operator Workflow Board Model

The operator-facing workflow board should stop treating one mixed
`Needs Attention` table as the primary surface for all active work.

The later board design should instead present a small set of clearer buckets:

- `Queue Auto-fix`
  - remediation-ready items the bot can pick up now
- `Needs Review`
  - items that require human investigation, manual follow-up, or blocked-state
    interpretation before automation should continue
- `In Flight`
  - items currently being processed or already represented by an active merge
    request
- `Completed`
  - recently resolved items that no longer require operator action

The workflow board should stay operator-oriented rather than source-oriented.
Its main job is to answer:

- what can automation act on now,
- what needs a human decision,
- what is already moving,
- what has recently finished.

Recommended first bucket mapping:

- `Queue Auto-fix`
  - `open`
- `Needs Review`
  - `failed`
  - later any explicitly blocked state that still requires a human recovery
    decision
- `In Flight`
  - `in_progress`
  - `mr_opened`
- `Completed`
  - `done`
  - show only the most recent completed items on the workflow board

Dismissed outcomes should stay visible, but they should not share the same
bucket as active human follow-up work.

Recommended later handling:

- `rejected`
  - treat as dismissed or out of scope for the current attempt rather than as
    active operator review work
- `ignored`
  - treat as intentionally excluded work, typically driven by policy or
    explicit automation scope choices
- later render a separate `Rejected / Ignored` or `Dismissed` bucket if
  operators still need lightweight visibility into those outcomes without
  polluting the active workflow board

This board split should not change the underlying lifecycle model by itself.
It is primarily a clearer presentation model over the existing dashboard item
states.

The first board redesign should also preserve visible transition intent:

- when remediation selects an item:
  - it moves from `Queue Auto-fix` to `In Flight`
- when remediation opens a merge request:
  - it remains in `In Flight`
- when reconciliation decides work should retry later:
  - it moves back to `Queue Auto-fix`
- when a later operator action explicitly requeues a reviewed item:
  - it may also move back to `Queue Auto-fix`
- when remediation or reconciliation produces a failure that still needs human
  interpretation:
  - it moves to `Needs Review`
- when the issue is truly resolved:
  - it moves to `Completed`

`Investigate Failure` should remain a next-step label inside `Needs Review`,
not a bucket of its own. The board should emphasize the kind of operator
attention required, while the row wording explains the likely next recovery
path.

The first board redesign should prefer explanation and structure over adding
new mutable operator controls. A later phase can add retry, reset, or requeue
commands once the board semantics and recovery explanations are stable.

## 13. Human Interaction Model

Humans should be able to:

- inspect all remediation-ready items on the dashboard,
- see which item is currently in progress,
- follow the merge request link for an opened remediation,
- understand whether a failed item needs investigation, retry, blocked follow-up,
  or manual handling,
- mark items ignored or rejected later when command-style controls are added.

The first implementation should remain machine-managed by default, with human
inspection and merge-request review as the main oversight mechanism.

Later operator controls should move items only through explicit state
transitions. In particular, an inspected failure should not become retryable
just because it was viewed; it should become retryable only when the failure
class and recovery rule support that transition.

## 14. Migration Model

Dashboard-backed remediation should become the primary remediation workflow
before live rollout and now stands as the only active remediation path.

The first version should therefore keep ownership simple:

- the dashboard-backed remediation workflow owns active execution transitions,
- Sonar dashboard sync remains the discovery producer for Sonar-derived items,
- later convergence of dashboard state with merged or closed merge requests is a
  separate reconciliation concern,
- remediation no longer depends on a separate direct Sonar execution path.

## 15. Dashboard Schema Evolution Hardening

The dashboard body should now be treated as a versioned operator surface rather
than as incidental markdown owned only by the latest renderer.

Operator-facing summaries should remain useful and readable, but they should be
understood as projections over canonical machine-readable state.

Recommended functional rules:

- stable machine-readable blocks remain the source of truth for workflow items
  and structured metadata
- human-readable workflow tables and summaries may evolve, but they should not
  become the only place where machine-managed meaning lives
- dashboard changes should prefer additive evolution, such as optional sections,
  optional columns, or new machine blocks, over abrupt shape replacement
- live upgrades should preserve operator continuity where possible instead of
  forcing dashboard recreation as the default recovery path
- unsupported or ambiguous older layouts should fail conservatively rather than
  silently dropping workflow meaning

This matters because the dashboard is now both:

- a machine-managed workflow surface, and
- an operator-visible control plane that may survive across multiple renderer
  versions.

Future renderer improvements should therefore be evaluated not only on whether
the new layout reads better, but also on whether older live dashboards can be
loaded, normalized, and safely rewritten into the newer presentation.

## 16. Success Criteria

The dashboard-backed remediation workflow is successful when:

- one supported dashboard item can be selected deterministically,
- remediation no longer depends on direct SonarQube intake for that item class,
- merge requests still contain the same quality and traceability as the current
  Sonar remediation flow,
- dashboard status updates remain accurate and understandable,
- unsupported or unsafe items are skipped cleanly instead of being forced
  through remediation.

## 17. Dashboard Contract Growth

The first item contract is intentionally narrow, but the platform direction now
includes future producers beyond SonarQube.

To keep the dashboard viable as a shared work queue, the contract should remain
clear about:

- which fields are universally required for every remediation-ready item,
- which fields are source-specific extensions,
- how new producers can add structured metadata without weakening the strict
  machine-managed format.

This avoids turning one flat item model into an overloaded bucket of optional
fields as more workflow types are added.

## 18. Traceability Expectations

Operators should be able to correlate one remediation attempt across:

- dashboard item ID,
- run summary,
- branch name,
- commit SHA,
- merge request URL.

## 19. Advisory Remediation Confidence

The remediation workflow may later expose an advisory confidence signal to help
operators understand how likely the bot thinks it can produce a safe and
bounded fix for the selected item.

This signal should remain advisory in the first version:

- it should not auto-merge changes,
- it should not replace human review,
- it should not automatically close dashboard items on its own.

The score should be accompanied by a short machine-generated reason so
operators can understand why the score was low or high instead of seeing an
unexplained number.

Recommended initial behavior:

- use a simple normalized score range such as `0.0` to `1.0`,
- store the score and reason on the dashboard item or associated workflow
  artifacts,
- surface the score for prioritization and operator awareness before using it
  as any stronger policy input.

Review-specific confidence should be defined in the pull-request review bot
functional design rather than here.

Those traceability fields should remain stable across normal success, failure,
and retry paths so the dashboard can act as a real operational control plane
rather than only a backlog view.
