# ZeroOne Ops Dashboard Policy Processing Technical Design

## 1. Scope

This document defines the technical design for a dedicated dashboard
policy-processing workflow in ZeroOne Ops.

It complements
[functional-design-dashboard-policy-processing.md](../functional/functional-design-dashboard-policy-processing.md),
which defines the operator-facing behavior and workflow intent.

This technical design focuses on:

- workflow boundaries,
- runner and command shape,
- deterministic note replay,
- idempotent dashboard updates,
- coordination with remediation and reconciliation.

## 2. Architectural Direction

Dashboard policy mutation should be processed by a dedicated workflow path.

The dashboard domain should keep these responsibilities separate:

- `dashboard_remediation_runner`
  - consumes current policy during item pickup and execution
- `dashboard_reconciliation_runner`
  - observes merge request and workflow state, then converges lifecycle state
- `dashboard_policy_action_runner`
  - processes operator-issued policy commands and updates canonical dashboard
    policy state

This keeps observed-state convergence separate from intentional operator
mutation.

## 3. Why A Separate Runner

The dedicated runner exists because policy mutation is not the same kind of
work as remediation or reconciliation.

Reconciliation answers questions like:

- did a merge request close,
- should an item reopen,
- is a retry now eligible,
- should a workflow item move to `done` or `failed`.

Policy processing answers questions like:

- did an operator disable `high`,
- did an operator exclude `sonarqube / python:S3776`,
- did an operator remove a prior exclusion.

These should not share one catch-all state machine.

## 4. Command And Runner Shape

Recommended first command shape:

- `zeroone-ops dashboard policy`

Recommended first CI/job shape:

- a dedicated dashboard policy job that can invoke
  `zeroone-ops dashboard policy` independently of remediation and
  reconciliation jobs.

Trigger-model note:

- the codebase should expose the runnable command and workflow path,
- the exact trigger mechanism is a runbook/deployment concern,
- schedules, manual runs, or webhook-triggered pipelines can all sit on top of
  the same command contract.

The runner should:

1. load config and state metadata,
2. load the dashboard issue,
3. fetch dashboard issue notes,
4. replay accepted strict policy commands,
5. render the updated canonical dashboard document,
6. update the dashboard issue only when the rendered document changed.

## 5. Canonical Data Flow

The canonical policy store remains the dashboard document policy state.

The dedicated policy-processing workflow should use this flow:

1. parse the existing dashboard body,
2. resolve canonical seeded policy state,
3. parse policy notes through `dashboard_policy_action_service`,
4. replay accepted actions deterministically into canonical policy state,
5. rebuild the rendered policy view from canonical state,
6. render the full dashboard document,
7. persist by updating the dashboard issue body.

The dedicated runner should not create a second authoritative store for policy
mutation results.

## 6. Idempotency Strategy

The first implementation should remain stateless and idempotent.

Recommended approach:

- replay the full bounded set of accepted policy notes on every policy run,
- sort accepted actions deterministically by `created_at` and `note_id`,
- let the latest valid command win for the same target,
- update the dashboard only when the rendered result changes.

Phase 6 decision:

- keep full note replay every run in the first implementation,
- do not add processed-note cursors while note volume is expected to remain
  small.

Why this is preferred first:

- no separate processed-note cursor is needed,
- the runner can recover naturally from retries,
- dashboard policy state remains derivable from the dashboard plus notes,
- note ordering semantics stay testable and explicit.

The workflow should not require per-note acknowledgement state in the first
implementation.

## 7. Validation Behavior

The dedicated runner should continue to use
`dashboard_policy_action_service` for:

- strict prefix matching,
- bounded grammar validation,
- malformed-command rejection,
- deterministic action extraction.

Phase 6 decision:

- keep the exact current `/zeroone policy` grammar in the first dedicated
  runner split,
- do not expand command coverage as part of the workflow-boundary change.

The runner should not re-implement command parsing itself.

This keeps policy validation logic concentrated in one service.

## 8. Coordination With DashboardService

The existing `DashboardPolicyService` already resolves canonical policy state
and rendered policy views.

Recommended Phase 6 use:

- the dedicated policy runner should reuse `DashboardService` and
  `DashboardPolicyService` rather than inventing a second render/update stack,
- the new runner should make policy processing explicit at the workflow level,
  not duplicate lower-level document orchestration.

This preserves current service boundaries while improving operational
separation.

## 9. Interaction With Reconciliation And Remediation

Expected boundaries:

- remediation reads the effective canonical dashboard policy during pickup,
- reconciliation updates lifecycle items based on observed workflow state,
- policy processing updates canonical dashboard policy state from operator
  commands.

Allowed overlap:

- all three workflows may load and render the same dashboard document.

Disallowed ownership drift:

- reconciliation should not mutate policy because it happened to read policy
  notes,
- remediation should not become responsible for applying operator comments,
- policy processing should not take ownership of lifecycle convergence.

## 10. Concurrency And Update Semantics

The first implementation can tolerate ordinary last-writer-wins dashboard
issue updates as long as every workflow:

- loads the latest dashboard state,
- recomputes deterministic canonical state,
- writes only its own derived current result.

Important guardrail:

- the policy runner must always derive policy state from the latest dashboard
  body plus current notes, not from stale in-memory assumptions.

If concurrent-update pressure grows later, a more explicit optimistic
concurrency or retry strategy can be added, but it is not required for the
first dedicated runner split.

## 11. Logging And Observability

The dedicated runner should log:

- number of notes fetched,
- number of prefixed commands seen,
- number of accepted commands,
- number of rejected prefixed commands,
- whether the dashboard issue was updated,
- the final policy-change run outcome.

This gives enough signal to operate the workflow without adding a second
operator-facing acknowledgement channel.

## 12. Future Extensions

Possible later additions:

- explicit acknowledgement notes for accepted or rejected policy commands,
- note-level processing summaries,
- richer policy command types such as bounded policy inspection,
- policy-run-specific metrics or dashboards,
- a future rename from `remediation.supported_severities` to a clearer
  bootstrap-only config name.

These should remain follow-up work, not blockers for the first dedicated
policy runner.
