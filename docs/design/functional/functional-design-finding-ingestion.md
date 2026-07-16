# ZeroOne Ops Finding Ingestion Functional Design

## 1. Scope

This document defines the product-facing design for moving ZeroOne Ops from a
source-specific intake model to generic finding ingestion.

The purpose of this design is to clarify what the product should mean by a
finding source and what must stay stable as new sources are added.

This is not a redesign of:

- review output,
- remediation execution,
- dashboard control-plane storage,
- GitHub or GitLab operator policy surfaces.

It is a design for how findings enter the product.

## 2. Problem

Today the active product experience is still closely associated with one source:

- SonarQube findings are discovered,
- SonarQube-derived items are synced into the dashboard,
- remediation then works from that inventory.

That works for the current rollout, but it creates a product limitation:

- adding another source can feel like adding another workflow instead of adding
  another input into one shared workflow system.

From a product point of view, that is the wrong mental model.

The product should not be:

- a SonarQube workflow with optional extras

It should be:

- a shared workflow platform that accepts findings from different sources and
  moves them through the same downstream inventory, policy, remediation, and
  control-plane model.

## 3. Product Goal

The product goal is to make finding source an input concern, not a workflow
identity.

The intended product shape is:

```text
Finding source
  -> normalized finding
  -> shared workflow inventory
  -> shared policy
  -> shared remediation selection
  -> shared control-plane lifecycle
```

What should stay stable:

- how findings appear in the workflow inventory
- how policy applies
- how remediation is selected
- how review and remediation projection flow through the control plane

What may vary by source:

- how findings are collected
- what raw metadata is available
- what source-specific identity or URLs exist

## 4. User-Facing Model

### 4.1 Source And Platform Are Different Things

This design treats repository platform and finding source as separate product
concepts.

Examples:

- GitHub repository with Ruff SARIF findings
- GitHub repository with CodeQL SARIF findings
- GitLab repository with SonarQube findings
- later, GitHub or GitLab repository with workflow-failure findings

The operator should not need to think of these as different remediation
products. They are the same remediation and control-plane product with
different finding inputs.

### 4.2 Shared Downstream Workflow

Once a finding is ingested, the downstream workflow should feel shared:

- the finding enters workflow inventory
- policy decides whether it is actionable
- remediation decides whether it is eligible for automation
- control-plane state reflects lifecycle and review outcomes

That means the product should avoid source-specific behavior in the main
operator flow unless it is truly necessary.

### 4.3 Source-Specific Metadata Is Secondary

Different finding sources may provide different metadata richness.

For example:

- SonarQube may provide a strong issue key and rule metadata
- SARIF may provide rule IDs, locations, and tool-specific properties
- workflow failures may provide job names or run URLs instead of code-rule IDs

The product should preserve useful metadata where it helps, but operators
should still see one shared model:

- what the finding is
- where it applies
- how severe it is
- whether it is in scope for automation

## 5. First Rollout

The first rollout should not remove the current SonarQube path.

Instead it should:

1. keep SonarQube as the first supported finding source
2. place SonarQube behind the new generic ingestion boundary
3. add one additional finding source for dogfooding on this repository

The first additional source should be chosen for practical feedback speed, not
for maximum ecosystem coverage.

The current preferred candidate is:

- Ruff via SARIF

Reason:

- it can run on this repository
- it produces structured output
- it provides a practical way to test generic ingestion plus GitHub
  control-plane/remediation behavior

## 6. Product Constraints

- generic finding ingestion should not broaden remediation safety boundaries
- adding a source should not create a second control plane
- the product should still present one shared workflow inventory
- source-specific collection details should not leak into the main operator
  workflow unless needed for understanding or traceability

## 7. Non-Goals

- replacing SonarQube immediately
- requiring SARIF for every source
- adding many new sources in the same rollout
- changing review product behavior as part of finding-ingestion work
- changing platform-specific operator command surfaces in this phase

## 8. Open Questions

- what minimum finding fields must always be visible to operators?
- how much source-specific metadata should be visible in the workflow inventory?
- how should the product describe source identity when multiple sources report
  similar issues?
- should different finding sources share the same queueing and prioritization
  rules by default, or are some source classes operator-tuned later?

## 9. Recommendation

The next implementation phase should treat generic finding ingestion as the new
product boundary and use one additional dogfooding source only after that
boundary exists.

That keeps the product moving toward:

- shared workflow behavior,
- source-agnostic downstream logic,
- and a clearer platform story beyond a SonarQube-first rollout.
