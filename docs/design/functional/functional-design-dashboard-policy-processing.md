# ZeroOne Ops Dashboard Policy Processing Functional Design

> **Status: Historical.** GitLab dashboard mode is deprecated compatibility
> behavior. For current issue-mode contracts, see the [design index](../README.md).

## 1. Purpose

Define the product behavior for a dedicated dashboard policy-processing
workflow in ZeroOne Ops.

The dashboard already acts as the operator-facing remediation policy surface.
Phase 6 should finish the workflow boundary by processing operator-issued
policy commands through a dedicated path instead of piggybacking on
remediation pickup or reconciliation runs.

## 2. Goals

- process operator policy changes independently of remediation and
  reconciliation schedules,
- keep policy mutation as a separate concern from observed workflow-state
  convergence,
- make policy processing deterministic, bounded, and easy to reason about,
- keep the dashboard policy surface responsive without requiring a remediation
  run to happen first,
- preserve one clear operator-facing control plane for policy.

## 3. Non-Goals

- redesigning the dashboard policy command grammar,
- adding free-form dashboard editing as a supported control path,
- changing hard safety boundaries,
- introducing operator acknowledgements or conversational note replies in the
  first version,
- solving multi-repository shared policy management.

## 4. Current Product Gap

Today the product can parse and apply strict `/zeroone policy ...` commands,
but that work is still coupled to normal dashboard load/update behavior.

This creates a workflow mismatch:

- remediation pickup is about selecting eligible work,
- reconciliation is about observed workflow state,
- policy mutation is about intentional operator commands.

The architecture is clearer if policy mutation has its own workflow path.

## 5. Primary User Stories

### 5.1 Fast Policy Change Application

As an operator, I want my dashboard policy comments to take effect without
waiting for a remediation or reconciliation run, so policy changes feel like a
first-class workflow rather than a side effect.

### 5.2 Predictable Workflow Boundaries

As a maintainer, I want policy mutation to live in a dedicated workflow, so
reconciliation stays focused on observed state and remediation stays focused on
consuming policy rather than mutating it.

### 5.3 Safe Invalid Command Handling

As an operator, I want malformed policy comments to be ignored or rejected
safely without affecting remediation lifecycle behavior, so policy mistakes do
not destabilize unrelated workflows.

## 6. Product Model

The dashboard domain should expose three distinct workflow roles:

1. remediation pickup and execution,
2. workflow-state reconciliation,
3. operator policy processing.

These roles interact with the same dashboard document, but they do not own the
same kinds of decisions.

Expected ownership:

- remediation owns item selection and execution against current policy,
- reconciliation owns observed lifecycle convergence,
- policy processing owns bounded operator-issued policy mutation.

## 7. Operator Command Scope

The first dedicated policy-processing workflow should continue to support the
existing strict operator command set:

- enable severity,
- disable severity,
- exclude issue class,
- remove issue-class exclusion.

The first version should not expand the policy grammar just because a new
runner exists.

## 8. Triggering Behavior

The dedicated policy workflow should be runnable intentionally, without
depending on remediation or reconciliation runs.

Expected first product behavior:

- a dedicated `zeroone-ops dashboard policy` command exists,
- a CI job may invoke that command independently of remediation and
  reconciliation jobs,
- it loads the dashboard issue and policy notes,
- it validates strict `/zeroone policy ...` comments,
- it applies accepted policy mutations into canonical dashboard policy state,
- it re-renders the dashboard when the canonical result changes.

This allows operators to treat policy processing as an explicit workflow.

Trigger-model note:

- the product requirement is that policy processing is independently runnable,
- the exact trigger shape is a deployment/runbook choice,
- teams may use schedules, manual runs, or webhook-triggered pipelines later
  without changing the core workflow contract.

## 9. Invalid And Repeated Commands

The workflow should remain conservative and deterministic.

Expected first behavior:

- malformed prefixed commands are rejected safely,
- unrelated comments are ignored,
- repeated valid commands are replayed deterministically,
- later valid commands win over earlier commands for the same policy target.

The first dedicated runner split should keep the exact current command grammar.
The runner split is a workflow-boundary change, not a command-surface expansion.

The operator should not need to understand hidden mutable state beyond the
visible dashboard policy result.

## 10. Operator-Facing Results

The first dedicated policy-processing workflow does not need to add a new note
reply surface.

Recommended first operator-facing result:

- the dashboard itself reflects the new canonical policy state,
- policy sections and grouped inventory update accordingly,
- no extra acknowledgement note is required for v1 of this workflow split.

This keeps the first implementation narrow and avoids introducing a second
feedback channel before it is clearly needed.

## 11. Product Guardrails

- direct markdown edits remain non-authoritative,
- reconciliation must not become a catch-all policy mutation engine,
- remediation must consume policy but not own policy mutation,
- policy processing must not widen hard safety boundaries,
- one operator comment workflow should not silently introduce a second policy
  authority path.

## 12. Rollout Direction

Recommended sequence:

1. finish dashboard-first policy authority,
2. add the dedicated policy-processing workflow,
3. keep the command grammar unchanged in the first runner split,
4. keep full note replay every run in the first version while note volume
   remains small,
5. observe whether explicit acknowledgements or richer policy note responses
   are needed later.
