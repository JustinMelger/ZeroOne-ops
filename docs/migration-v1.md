# Migrating To V1

V1 supports GitHub and GitLab issue mode only. Legacy GitLab dashboard runtime,
review mirroring, commands, and local dashboard state models have been removed.
The application never migrates, closes, relabels, rewrites, or deletes remote
dashboard issues. They remain readable history.

## Commands And Configuration

Update CI jobs and scripts before upgrading:

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
than silently selecting a new authority. Other documented configuration aliases
are unaffected by this retirement.

## Operator Cutover

1. Stop old dashboard jobs and account for existing linked MRs, active claims,
   blocked work, and dismissed findings before upgrading.
2. Confirm `remediation.bootstrap_severities`, finding sources, capacity, and
   credentials are appropriate for the new issue control plane.
3. Set the mode to `"issues"` or omit it, and install the supported CI template
   using the neutral commands.
4. Run finding sync. It uses current findings and normal promotion rules to
   populate policy and authoritative work-item issues.
5. Reapply desired policy overrides and exclusions through the dedicated policy
   issue. Historical policy, linkage, claims, dismissals, and recovery records
   are not transferred automatically; existing findings may otherwise be selected
   again under their current identities.

Operators may manually label and close the old dashboard after confirming the
cutover, but ZeroOne Ops does not perform that cleanup. Operational summaries
remain supported read-only derived views; they are not the retired dashboard.

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

Confirm operator cutovers before tagging v1. Run the GitHub and GitLab live
checks for same-request revisions, failed-revision recovery, and manual
merge-conflict recovery in addition to automated verification. This document
does not claim those live checks have completed.
