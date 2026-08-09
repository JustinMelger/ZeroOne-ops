# GitLab Issue Control Plane Functional Design

## Purpose

Replace the growing all-in-one GitLab dashboard issue with a GitLab-native
control plane that has the same operator shape as the GitHub implementation:

- one policy issue for repository-wide automation policy;
- one authoritative issue for each promoted remediation work item; and
- an optional derived operational summary.

The goal is operational clarity, not storage uniformity. GitLab continues to
use GitLab issues, labels, merge requests, and project-member authorization.

## Problem

The current GitLab dashboard is both the authoritative state store and the
operator overview. As a repository accumulates findings and lifecycle updates:

- its rendered body becomes difficult to scan;
- GitLab records a visible update history for repeated dashboard changes;
- policy and recovery commands become hard to find and use; and
- changing one item requires rewriting a document that contains unrelated
  work.

Section limits make the body smaller, but do not solve the authority and
interaction problem.

## Goals

- make every promoted remediation item independently inspectable and actionable;
- keep policy commands on a small, stable issue;
- preserve shared policy, remediation, recovery, review-projection, and
  lifecycle behavior across GitLab and GitHub;
- retain GitLab-native authorization and merge-request traceability;
- allow a compact overview without making it authoritative; and
- switch existing repositories without two sources of truth.

## Non-Goals

- replace GitLab issues with GitHub-shaped storage or a database;
- create a work-item issue for every backlog-only finding;
- migrate historical dashboard rows into new issues by default;
- change remediation eligibility, model behavior, or validation-loop rules;
- infer or silently transfer active execution state during cutover.

## Target Operator Experience

### Policy

One open GitLab issue, labelled `zeroone-policy`, is authoritative for
repository-wide severity and issue-class policy. Maintainers and Owners post
the existing strict `/zeroone policy ...` commands there.

Its body is compact and machine-managed. It shows current policy, exclusions,
and a command reference. Comments are the command audit trail; direct body
edits are not authoritative.

### Work Items

Each policy-promoted finding has one authoritative open GitLab issue labelled
`zeroone-work-item`, `zeroone-source:<source>`, and
`zeroone-status:<status>`. Its body contains:

- a concise finding and location;
- current lifecycle state and remediation category;
- linked merge request and review projection when present;
- the latest execution failure when blocked; and
- a collapsed machine state block containing `WorkItemState`.

Blocked work items show their recovery commands directly on the issue:

```text
/zeroone remediation requeue
/zeroone remediation dismiss
```

The affected issue identifies the item, so the GitLab command form matches
GitHub. The legacy dashboard command form remains only while dashboard mode is
active.

Completed and dismissed remediation issues are closed after their terminal
machine state is persisted. Dismissed issues remain searchable tombstones so a
later finding sync does not recreate them.

## GitLab Command Processing

GitLab issue mode uses one scheduled/manual control-plane job because it does
not have GitHub's issue-comment workflow trigger. Each run processes:

1. policy commands on the dedicated policy issue;
2. recovery commands on open `zeroone-work-item` issues; and then
3. normal remediation intake.

Recovery discovery scans only labelled open work-item issues, paginates the
issue list, and reads their notes. Accepted recovery events retain the note ID,
so later polling runs do not replay a command. The initial schedule cadence is
every 30 minutes; manual execution remains available for operator follow-up.
The installed GitLab CI template exposes this as one
`zeroone_ops_control_plane` job. It runs policy processing, recovery
processing, and remediation sequentially after finding sync, when that job is
enabled. A GitLab schedule enables it with
`RUN_ZEROONE_OPS_CONTROL_PLANE=true`; the same variable exposes a manual
default-branch job for operator follow-up.

### Operational Summary

In issue mode, the `ZeroOne Ops Summary` issue, indexed with the
`zeroone-summary` label, is a derived, read-only view.
It contains counts, active merge requests, recent outcomes, and a link to the
policy issue. It is never a command surface or source of lifecycle state.

## Authority Model

| Concern | Authoritative GitLab record | Derived view |
|---|---|---|
| Repository policy | Policy issue machine state and authorized comments | Operational summary policy link |
| Remediation lifecycle | Work-item issue machine state | Operational summary counts and entries |
| Finding backlog | Finding sync result | Optional summary counts only |
| Recovery | Authorized comment on the affected work-item issue | Rendered recovery instruction |

No workflow may write both the dashboard and issue control planes as
authoritative state in the same mode.

## Cutover And Rollout

Introduce an explicit GitLab control-plane mode:

- `dashboard`: current behavior for existing repositories; and
- `issues`: policy issue plus authoritative work-item issues, with an optional
  derived summary.

New issue-mode rollouts begin with empty GitLab issue control-plane records.
Existing dashboard repositories use switch-and-sync by default:

1. Confirm `remediation.bootstrap_severities` expresses the desired initial
   issue-mode policy.
2. Change `gitlab.control_plane_mode` to `issues`.
3. Run normal finding sync. Issue mode creates its policy issue from bootstrap
   configuration, and current upstream findings are materialized through their
   normal stable identity and promotion rules.
4. Freeze the old dashboard as a legacy read-only record. It is not rewritten,
   reconciled, or used for commands after the switch.

After cutover, apply the `zeroone-legacy-dashboard` label and close the legacy
dashboard issue. It remains readable historical context without competing with
the policy issue or active work-item issues.

During the bounded live-testing rollout, changing `gitlab.control_plane_mode`
to `issues` explicitly accepts that active claims, linked merge requests,
blocked or dismissed work, recovery history, and other dashboard lifecycle
state are not transferred. Participating repositories must receive that
rollout notice.

Dashboard policy commands and exclusions are not transferred. Operators use the
new policy issue to apply any desired overrides after cutover. This keeps the
new control plane seeded by explicit configuration rather than historical
dashboard state. Unrelated dashboard discussion remains historical context and
is not linked into issue mode.

A later narrow active-state transfer may be designed if broader rollout
experience shows it is necessary. It is not part of the default cutover and
must never become a broad historical dashboard migration.

## Dashboard Support Window

Dashboard mode remains fully supported through Phase 8 implementation and live
validation in at least two GitLab repositories. Once issue mode has completed
that rollout:

1. New GitLab examples default to issue mode.
2. Dashboard mode becomes maintenance-only: compatibility, migration support,
   and correctness fixes continue, but no new workflow features are added.
3. Dashboard mode remains available for two minor releases.
4. It is removed in the next planned breaking release after that window.

The dashboard remains readable after cutover as historical context, but it is
not an active control plane in issue mode.

## Behavioral Parity

GitLab issue mode must match GitHub behavior where the workflow semantics are
shared:

- promotion from normalized findings follows the same policy;
- one work item is claimed per remediation run;
- merge-request state drives the same lifecycle transitions;
- recovery is explicit, authorized, and event-scoped;
- review projection updates the work item linked to the merge request; and
- terminal work items close only after state persistence.

Provider differences remain intentional:

- GitLab uses project Maintainer/Owner authorization, not GitHub admin roles;
- GitLab issue and merge-request URLs, labels, and API semantics remain local;
- GitLab can keep the operational summary disabled initially; and
- existing dashboard mode remains available during the cutover window.

## Success Criteria

- a policy command is usable without searching through a dashboard history;
- a blocked item is requeued or dismissed from its own issue;
- updating one work item does not rewrite unrelated work-item state;
- GitLab lifecycle and recovery outcomes match GitHub for equivalent inputs;
- the dashboard no longer grows as the active authoritative inventory.
