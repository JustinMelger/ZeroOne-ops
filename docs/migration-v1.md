# Migrating To V1

V1 supports GitHub and GitLab issue mode only. Legacy GitLab dashboard runtime,
review mirroring, commands, and local dashboard state models have been removed.
The application never migrates, closes, relabels, rewrites, or deletes remote
dashboard issues. They remain readable history.

## Commands And Configuration

Update CI jobs and scripts before upgrading:

The supported installation templates now pin image version `1.0.0`. Update any
project, group, or repository `ZERO_ONE_OPS_VERSION` override too; it takes
precedence over the template default. Use the stable pin only after the v1 image
has been published, or override it with the exact RC tag while testing.

| Removed command | Replacement |
| --- | --- |
| `zeroone-ops dashboard sonar` | `zeroone-ops findings sync` |
| `zeroone-ops dashboard remediate` | `zeroone-ops remediation run` |
| `zeroone-ops dashboard reconcile` | `zeroone-ops work-items sync-status` |
| `zeroone-ops dashboard policy` | `zeroone-ops policy run` |

There are no forwarding aliases. GitLab's `zeroone-ops control-plane run`
continues to process policy, recovery, and remediation in that order, followed
by one derived-summary refresh. Lifecycle reconciliation remains separate.

`gitlab.control_plane_mode` may be omitted or set to `"issues"`. An explicit
`"dashboard"` value fails configuration loading with migration guidance rather
than silently selecting a new authority.

## Configuration Alias Removal

Replace these retired keys before upgrading:

| Removed key | Canonical replacement |
| --- | --- |
| `review.platform` | `platform` |
| `gitlab.target_branch` | `remediation.target_branch` |
| `remediation.supported_severities` | `remediation.bootstrap_severities` |
| root `validation_setup_commands` | `remediation.validation_setup_commands` |
| root `validation_commands` | `remediation.validation_commands` |

The old key must be removed, not merely accompanied by its replacement. Null
and empty values are rejected too. The CLI exits with status `2` and field-specific
replacement guidance, without printing configured values or making provider calls.
Move the values manually; there is no automatic migration or file rewriting.
Canonical defaults and provider requirements remain unchanged. Deprecated but
functional context/helper tuning fields retain their existing warning behavior.

V1 also removes two review settings that never affected execution:
`review.max_review_feedback_retries` and `review.skip_draft_merge_requests`.
Remove both keys from existing configuration. They now fail strict validation
with field-specific removal guidance rather than being silently ignored.
There is no replacement retry setting. Control whether draft requests trigger
review through provider CI rules.

## Operator Cutover

1. Stop old dashboard jobs and keep finding-sync and remediation schedules paused
   throughout cutover. Account for existing linked MRs, active claims, blocked
   work, and dismissed findings before upgrading.
2. Confirm `remediation.bootstrap_severities`, finding sources, capacity, and
   credentials are appropriate for the new issue control plane.
3. Complete the local-state cleanup below, set the mode to `"issues"` or omit
   it, and install the supported CI template using the neutral commands. Keep
   automatic execution paused.
4. Run `zeroone-ops policy run` to establish the dedicated policy issue. Reapply
   desired policy overrides and exclusions there, then run `zeroone-ops policy run`
   again to process the commands. Verify the effective policy before promotion.
5. Generate current target-branch scanner reports, then run
   `zeroone-ops findings sync --dry-run` and inspect the proposed selection.
   Run `zeroone-ops findings sync` only after confirming it is appropriate.
6. Inspect the resulting work items before enabling remediation and resuming
   schedules. Historical dashboard policy, linkage, claims, dismissals, and
   recovery records are not transferred automatically; existing findings may
   otherwise be selected again under their current identities.

Operators may manually label and close the old dashboard after confirming the
cutover, but ZeroOne Ops does not perform that cleanup. Operational summaries
remain supported read-only derived views; they are not the retired dashboard.

## Batching For Existing Issue-Mode Installations

V1 groups compatible new findings from the same source, file, and rule into one
work item and one one-file PR/MR. `remediation.max_findings_per_work_item` defaults
to `5`. Set it to `1` before the first v1 finding sync to prevent multi-member
batches:

```json
{
  "remediation": {
    "max_findings_per_work_item": 1
  }
}
```

Merge this setting into existing configuration; do not replace the entire file.
Existing single-finding issues remain independent, and existing batches are not
resized when the setting changes. `remediation.max_active_work_items` still
limits active work items, not individual findings: a batch consumes one slot.
Generate current target-branch reports before sync and inspect a dry run before
resuming automation. Existing issue-mode policy remains authoritative; dashboard
policy cutover is unnecessary for installations already using issue mode.

## Local State Cleanup

V1 refuses a state file containing nonempty `dashboard_items` or
`remediation_exclusions`, a non-null `active_dashboard_item_id`, or a run with a
non-null `dashboard_item_id`. The CLI exits with status `2`, naming the file and
fields without printing their contents. It does not modify the file or make
provider calls. This also applies to dry runs.

For the configured `state.path` (default `.zeroone-ops-state.json`):

1. Stop jobs that may write the state file and make an external backup.
2. Remove the top-level `dashboard_items`, `active_dashboard_item_id`, and
   `remediation_exclusions` fields.
3. Delete only run records whose `dashboard_item_id` is non-null. These are
   dashboard-associated runs and will no longer be retained by the application.
4. Retain other runs, repository metadata, `issues`, and `reviews`, including
   review continuity and pending projection-repair evidence. Do not reset the
   entire state file as a substitute for this cleanup.
5. Retry the intended workflow after validating the edited JSON.

Old issue-mode files containing only empty/null dashboard defaults still load;
those obsolete fields are omitted on normal save. Historical issue-mode failures
with stage `dashboard_update` decode as `control_plane_update`. Existing remote
issue machine state, review evidence, and recovery/publication retries remain
unchanged. No migration command or automatic state/history transfer is provided.

## Release Validation

The maintainer confirmed latest-RC live validation on GitHub and GitLab on
2026-10-29; acceptance is recorded in the [roadmap](roadmap.md#v1-release-readiness).
This does not migrate other installations or replace their cutover checks.
Confirm issue-mode cutover and local-state cleanup for each installation before
enabling v1 automation.
