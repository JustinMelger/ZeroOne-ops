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

### 8.5 Dashboard Lifecycle Updater

Responsible for:

- transitioning dashboard item statuses,
- recording merge request links,
- moving failed or rejected items out of active sections,
- keeping the dashboard in sync with remediation progress.

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

## 12.1 Stale In-Progress Recovery

The first implementation should define what happens when a run marks an item
`in_progress` and then does not finish cleanly because the job is canceled, the
runner crashes, or the process loses network access mid-flight.

At minimum, operators should be able to tell:

- whether the item is still actively being processed,
- whether the item should be moved back to `open`,
- whether the item should be left `in_progress` for manual follow-up.

The workflow should prefer explicit recovery rules over leaving stale
`in_progress` items ambiguous forever.

## 13. Human Interaction Model

Humans should be able to:

- inspect all remediation-ready items on the dashboard,
- see which item is currently in progress,
- follow the merge request link for an opened remediation,
- mark items ignored or rejected later when command-style controls are added.

The first implementation should remain machine-managed by default, with human
inspection and merge-request review as the main oversight mechanism.

## 14. Migration Model

Dashboard-backed remediation should be introduced gradually:

1. keep direct Sonar remediation available during migration,
2. add dashboard-backed remediation for the same narrow Sonar-derived item
   class,
3. compare outcomes and operational friction,
4. make dashboard-first remediation the default once behavior is stable.

This avoids forcing the core remediation path to depend on the dashboard before
its state transitions and retention rules are mature enough.

During migration, the platform should also define which path owns a given item.

The migration model should make it clear:

- when direct Sonar remediation is allowed to work on an issue,
- when dashboard-backed remediation is allowed to work on the corresponding
  dashboard item,
- how duplicate work is prevented while both paths remain available.

## 15. Success Criteria

The dashboard-backed remediation workflow is successful when:

- one supported dashboard item can be selected deterministically,
- remediation no longer depends on direct SonarQube intake for that item class,
- merge requests still contain the same quality and traceability as the current
  Sonar remediation flow,
- dashboard status updates remain accurate and understandable,
- unsupported or unsafe items are skipped cleanly instead of being forced
  through remediation.

## 16. Dashboard Contract Growth

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

## 17. Traceability Expectations

Operators should be able to correlate one remediation attempt across:

- dashboard item ID,
- run summary,
- branch name,
- commit SHA,
- merge request URL.

Those traceability fields should remain stable across normal success, failure,
and retry paths so the dashboard can act as a real operational control plane
rather than only a backlog view.
