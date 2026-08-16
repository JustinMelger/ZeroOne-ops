# GitLab Issue Control Plane Technical Design

## Scope

Implement the functional contract in
[functional-design-gitlab-issue-control-plane.md](../functional/functional-design-gitlab-issue-control-plane.md).

This is a provider-local storage cutover over existing shared control-plane
models. It must not make GitLab code depend on GitHub clients, issue types, or
authorization semantics.

## Reuse Boundary

| Existing boundary | Reuse in GitLab issue mode |
|---|---|
| `WorkItemState`, `WorkItemSourceRef`, `RecoveryEvent` | Canonical persisted work-item payload and identity |
| `FindingWorkflowPolicyService` | Finding promotion and fresh-attempt eligibility |
| `PolicyActionService`, `PolicyProcessingService` | Strict policy parsing and replay |
| `RecoveryDecisionService` | Dismiss/requeue decisions and stale-command protection |
| `PublicationRetryService` | Verified branch publication retry |
| `RemediationWorkItemPromotionService` | Shared durable-work promotion boundary |
| `ChangeRequestState` and `ChangeRequestRef` | Merge-request lifecycle input and traceability |
| Existing remediation execution/publish services | One-item claim, patch, validation, and publication flow |

The existing `GitHubWorkItemReconciliationService` is logically shared but
named provider-local. Extract its pure transition decision into a neutral
`WorkItemChangeRequestReconciliationService` before both providers consume it.
GitHub retains a thin adapter during that extraction.

## Provider-Local GitLab Components

Add provider-local components by concern, parallel to the GitHub map:

```text
providers/
  gitlab_work_item_client.py
  gitlab_policy_client.py

services/control_plane/
  policy/
    gitlab_policy_issue_parser.py
    policy_issue_renderer.py
    gitlab_policy_issue_store.py
    gitlab_policy_issue_service.py
    gitlab_policy_processing_runner.py
  work_items/
    gitlab_work_item_parser.py
    gitlab_work_item_renderer.py
    gitlab_work_item_lookup_service.py
    gitlab_work_item_upsert_service.py
    gitlab_work_item_service.py
    gitlab_finding_sync_service.py
    gitlab_remediation_intake_service.py
    gitlab_work_item_lifecycle_service.py
    work_item_recovery_command_parser.py
    gitlab_work_item_recovery_service.py
    gitlab_work_item_recovery_runner.py
  overview/
    gitlab_operational_summary_*  # deferred until the work-item flow is proven
```

Do not add GitLab issue-mode behavior under `services/dashboard/`. That package
remains the legacy dashboard implementation until the cutover window ends.

## GitLab Transport Requirements

`GitLabDashboardClient` already supports issue creation, exact open-issue
lookup, body updates, notes, and membership lookup. Preserve that client for
dashboard mode. Add dedicated issue-control-plane transport rather than
silently broadening dashboard semantics.

The new client needs:

- paginated open and closed issue listing by labels;
- issue creation and full update of title, description, and labels;
- issue closure after persisted terminal state;
- issue-note listing and membership access lookup; and
- safe project-path encoding and consistent `GitLabClientError` translation.

Extend `GitLabIssueInfo` with labels, open/closed state, and timestamps. Keep
the existing dashboard consumer compatible while those fields are introduced.

## Persistence Contract

Use the same structured `WorkItemState` JSON payload as GitHub, in a
GitLab-specific renderer/parser envelope. The renderer owns human Markdown;
the parser validates only the machine state block.

Work-item lookup rules:

1. List only issues with the authoritative `zeroone-work-item` label.
2. Parse the machine block independently per issue; log malformed records and
   continue scanning.
3. Match identity with `WorkItemState.identity_key`, not title, label order, or
   source display text.
4. Require exactly one matching authoritative record. Log and return no match
   for duplicates rather than updating an arbitrary issue.
5. Search closed `zeroone-status:dismissed` issues for a matching identity
   before creating a new issue, preserving durable suppression.

Use labels as a provider-native index and human filter, not as the canonical
state. The machine state remains authoritative.

## Policy Issue Contract

The GitLab policy issue mirrors the GitHub provider-local policy pattern:

- lookup/create a single open `zeroone-policy` issue;
- parse its persisted `PolicyState` machine block;
- list and authorize issue notes through the existing Maintainer/Owner rule;
- replay authorized comments with `PolicyProcessingService`; and
- render the compact policy body and command reference.

The current dashboard policy view builder can remain the source for shared
severity and issue-class presentation initially. Rename it only if reuse proves
it is not dashboard-specific.

## Work-Item Flow

1. Finding sync loads canonical policy from the GitLab policy issue.
2. Shared policy decides promoted versus backlog-only findings.
3. GitLab finding sync creates or refreshes only promoted work-item issues.
4. Remediation intake finds one open, approved GitLab work-item issue and
   claims it through a persisted `WorkItemState` update.
5. Remediation execution publishes a GitLab merge request and projects the
   link, review result, and execution outcome onto that issue.
6. Lifecycle reconciliation reads linked merge-request state and applies the
   neutral reconciliation decision.
7. Terminal `completed` and `dismissed` issues are closed after their final
   machine state is written.

Control-plane projection failures remain best effort and must not replace the
primary remediation outcome.

## Recovery And Authorization

Issue mode accepts `/zeroone remediation requeue` and
`/zeroone remediation dismiss` only on the affected GitLab work-item issue.
The adapter must:

1. process the triggering note once;
2. authorize the author as Maintainer or Owner;
3. verify the current work-item fingerprint before applying the action;
4. persist the shared recovery decision; and
5. leave patch generation and execution to the normal remediation job.

This makes GitLab recovery event-scoped like GitHub and removes the need for a
dashboard item ID in the command.

## Command Polling

Add one GitLab scheduled/manual CI job, `zeroone_ops_control_plane`. It runs
the combined command, which processes policy, recovery, and remediation in this
order and refreshes the derived operational summary once afterward:

```text
zeroone-ops control-plane run
```

It uses the remediation resource group, Git author configuration, and
authenticated remote. It optionally needs finding sync so remediation acts on
fresh inventory when that job is present. Keep lifecycle reconciliation as a
separate job.

Recovery processing lists only paginated open issues carrying the
`zeroone-work-item` label. It loads notes for each candidate issue and skips a
note whose ID is already present in the bounded `WorkItemState.recovery_events`
history. It must not inspect unrelated project issues or replay commands from
closed work-item issues.

GitLab schedules are configured outside YAML. The initial schedule runs every
30 minutes with `RUN_ZEROONE_OPS=true`; the same variable exposes
a manual default-branch job for operator follow-up. The CI job itself does not
interpret `gitlab.control_plane_mode`: each invoked command selects exactly one
authority from that configuration, preventing dual writes.

## Cutover Implementation

Use `issues` as the default for `gitlab.control_plane_mode`. `dashboard`
remains an explicit legacy compatibility mode for repositories that have not
completed their cutover.

Cutover is operator-controlled:

1. set the desired `remediation.bootstrap_severities` in configuration;
2. set `gitlab.control_plane_mode` to `issues`; and
3. run normal finding sync, which creates the policy issue from bootstrap
   configuration and materializes current promoted findings.

No dashboard work-item records are copied during the default cutover. During
bounded live testing, the operator's explicit config switch accepts that active
claims, linked merge requests, blocked or dismissed work, recovery history, and
other dashboard lifecycle state are reset rather than transferred. Rollout
communication must make that consequence clear. A later active-state transfer
is a separate, explicit design if broader rollout experience shows it is
necessary.

After the switch, label the dashboard issue `zeroone-legacy-dashboard` and
close it. Closing is a provider-local presentation action only: the issue stays
readable, and no new control-plane workflow reads or writes it.

Dashboard policy state and comment history are not transferred. Operators use
the new GitLab policy issue to apply post-cutover overrides through the normal
command path. A future narrow protected-state transfer may attach legacy
dashboard provenance only to the work-item issue created from that specific
dashboard item; it must not copy or link unrelated dashboard discussion.

No dual-write path is permitted. The regular runners select exactly one
authority based on `gitlab.control_plane_mode`.

## Delivery Slices

### Phase 8a: Neutral Seams And GitLab Issue Transport

- extract neutral linked-change-request reconciliation;
- add GitLab issue-mode transport and richer issue model fields;
- add parser/renderer/store contracts with malformed-record handling; and
- retain dashboard behavior unchanged.

### Phase 8b: GitLab Policy Issue

- implement policy issue lookup, rendering, note authorization, and replay;
- wire GitLab issue mode to load policy from that issue; and
- add GitLab CI policy command processing for the policy issue.

### Phase 8c: GitLab Work-Item Publication And Intake

- materialize promoted findings as work-item issues;
- add safe identity lookup, claim, merge-request link, and review projection;
- add GitLab CI finding sync and remediation jobs for issue mode.

### Phase 8d: Lifecycle And Recovery

- reconcile GitLab merge requests and close terminal work-item issues;
- add event-scoped work-item recovery commands;
- live-test merge, closed-unmerged, blocked, dismissed, and stale-claim paths.

### Phase 8e: Optional Summary And Dashboard Retirement

- add a compact derived GitLab operational summary only after work-item use is
  proven;
- make dashboard mode maintenance-only after issue mode is live-validated in
  at least two GitLab repositories;
- remove dashboard-mode examples after that rollout;
- retain dashboard compatibility for two minor releases; and
- retire dashboard-only runners and compatibility parsing in the next planned
  breaking release after that window.

### Phase 8e: Operational Summary Implementation Plan

The GitLab summary is a derived, read-only operator view. It must never become
a policy command surface, lifecycle authority, or a second work-item store.
Work-item issues, the policy issue, and the latest successful finding sync
remain authoritative.

1. Extract the shared summary core from the GitHub implementation.
   - Move the view models, bounded entry and count rules, latest-finding-sync
     observation, Markdown safety rules, renderer, parser, and view builder to
     provider-neutral modules under `services/control_plane/overview/`.
   - Define a narrow normalized input for an issue-backed work item so the
     builder does not import GitHub or GitLab lookup result types.
   - Keep bounded lists: at most ten active change requests and five recent
     terminal outcomes. Show an omitted-entry count rather than growing the
     summary issue without bound.

2. Preserve provider-native presentation through a small vocabulary contract.
   - The shared renderer accepts provider-local terms for active change
     requests and their empty state.
   - GitHub retains its existing `pull request` wording and rendered shape.
   - GitLab renders `merge request` wording without duplicating summary logic.

3. Keep issue transport provider-local.
   - Adapt the existing GitHub store and service to the shared core without
     changing GitHub title, label, lookup, or best-effort semantics.
   - Add `GitLabOperationalSummaryStore` and service using the dedicated GitLab
     issue-control-plane client, with exact open title-and-label lookup,
     create, and full body update.
   - Use the same stable title and `zeroone-summary` label on both providers;
     label and title are discovery indexes, not authoritative state.

4. Publish only after successful authoritative operations.
   - A successful finding sync supplies a new latest-finding-sync observation.
   - Policy, remediation, recovery, and lifecycle paths refresh the summary
     while preserving its previously parsed observation when they have no new
     finding-sync result.
   - Summary publication is best effort: transport, parsing, or rendering
     failure is logged and does not replace the primary workflow outcome.
   - GitLab publication runs only when `gitlab.control_plane_mode` is `issues`;
     legacy dashboard mode receives no summary writes.

5. Verify in layers.
   - Unit-test shared builder, renderer, and parser equivalently for GitHub and
     GitLab vocabulary.
   - Unit-test GitLab store exact lookup, create/update/unchanged behavior, and
     malformed persisted observation handling.
   - Add runner integration coverage for finding sync, remediation transition,
     and lifecycle refresh with summary failure remaining non-fatal.
   - Live-test one GitLab issue-mode project before making the summary part of
     the standard GitLab installation template.

## Verification

- unit-test parser/renderer round trips, identity lookup, duplicate rejection,
  state preservation, lifecycle transitions, and recovery authorization;
- integration-test finding sync, remediation, review projection, and lifecycle
  with GitLab issue transport fakes;
- live-test one promoted finding through merge-request creation, review,
  merge, and terminal issue closure; and
- confirm policy and recovery commands are usable without navigating an
  ever-growing dashboard body.
