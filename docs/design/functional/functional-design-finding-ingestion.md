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

### 4.3 Shared Remediation Eligibility

Automation eligibility must be decided from shared normalized finding semantics,
not the source that reported the finding.

The first supported shared category is `static_analysis_fix`. Both SonarQube
code-smell findings and SARIF lint findings normalize to that category.

Existing dashboard records using the prior `code_smell_fix` name remain
eligible as a compatibility alias, but new normalized findings must use
`static_analysis_fix`. Source-local metadata remains available for traceability
and prompt shaping, not as an eligibility gate.

### 4.4 Source-Specific Metadata Is Secondary

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

Status after dogfooding on July 24, 2026:

- Ruff via SARIF now ingests successfully on this repository
- the first live dogfood pass confirmed two normalized findings from the
  `samples/ruff_findings` fixture path
- the next rollout question is no longer whether SARIF can enter the system,
  but how normalized findings should become visible and actionable on GitHub

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

### 8.1 Locked Decision: Shared Identity Model

The product should use one shared concept of issue identity across:

- finding ingestion
- workflow inventory and control-plane tracking
- review continuity and overlap matching

If a source exposes a strong native finding key, that key should be kept and
used.

If a source does not expose a strong durable key, the product should derive a
fallback identity using the same normalized matching rules already used for
review overlap.

This keeps the operator workflow consistent:

- the same underlying issue is less likely to appear as unrelated items across
  different source types
- continuity and remediation tracking use the same identity logic
- adding new sources such as Ruff SARIF does not require inventing a separate
  queue identity model

This is a product-level consistency rule, not a requirement that every source
look like SonarQube or SARIF internally.

### 8.2 Locked Decision: Minimum Shared Finding Shape

Every normalized finding should carry one small shared shape that downstream
workflow logic can depend on regardless of source.

The required fields are:

- stable finding identity
- source identity
- severity
- title
- summary
- repository-relative path
- optional line or region
- remediation-relevant context

This is the minimum shared contract for product behavior.
Anything beyond that should be treated as optional source detail rather than as
part of the universal operator workflow model.

### 8.3 Locked Decision: Remediation Context Stays Structured and Small

The remediation-relevant part of a finding should not be an unbounded metadata
bag.

Instead, normalized findings should carry a small structured remediation context
object with only the fields selection and remediation execution actually use.

That keeps the operator workflow predictable and prevents each source from
smuggling tool-local shape into the product boundary.

### 8.4 Locked Decision: Collection Metadata Lives Beside Findings

The product should treat ingestion as returning both:

- normalized findings
- bounded collection metadata

That metadata supports traceability and diagnostics such as:

- which source revision was collected
- which artifact or scan was used
- whether the collection produced bounded warnings or partial results

This information should live at the collection level instead of inflating every
normalized finding with scan-local details.

### 8.5 Locked Decision: Source Metadata Is Present but Not Workflow-Defining

Some finding sources expose useful extra information that the product should not
discard, but that information should not define the shared workflow model.

So:

- normalized findings may carry optional source-specific metadata
- the main operator workflow should not depend on that metadata by default
- source metadata is primarily for traceability, diagnostics, and detailed views

This keeps the product boundary stable while still preserving source-local
useful detail for later inspection or enhancement.

### 8.6 Locked Decision: One Shared Default Workflow Policy

Once findings are normalized, the product should treat them as entering one
shared workflow by default.

That means:

- the same queueing and promotion rules apply first regardless of source
- the same lifecycle and control-plane behavior applies after promotion
- source-specific workflow tuning is a later explicit decision, not the default

That shared workflow rule does not mean every downstream action widens at the
same time.

For rollout safety:

- normalized findings should first become visible in the shared operator
  workflow
- repeated sync and lifecycle reconciliation should then be validated
- remediation widening should only follow once visibility and lifecycle
  behavior are trusted

### 8.9 Locked Decision: SARIF Enters Through Artifact Paths, Not Tool Execution

For the first dogfooding slice, the product should treat SARIF as an artifact
input, not as a request to run Ruff or another analyzer itself.

That means:

- the repository pipeline or local workflow generates the SARIF artifact
- ZeroOne Ops reads the artifact from configured file paths
- the shared workflow begins at normalized findings, not at analyzer execution

The operator-facing config should therefore use a source-local `sarif` block
with explicit artifact and stable source-identity declarations, rather than
attaching the path to review or remediation settings.

Each configured artifact represents one logical tool source. Its declared
identity keeps an empty scan attributable to the same source as earlier
non-empty scans. If a non-empty artifact identifies a different tool source,
the collection is treated as non-authoritative and cannot reconcile prior
findings as stale.

This keeps the product boundary general enough for:

- Ruff on Python repositories
- CodeQL or Semgrep on other repositories
- later multi-tool SARIF inputs without renaming the config shape

This is important for product clarity.
If findings are normalized but immediately diverge into source-local workflow
rules, then the operator does not actually get a shared ingestion model.

### 8.10 Locked Decision: GitHub Visibility Precedes Remediation Widening

After the first successful Ruff SARIF dogfood run on Friday, July 24, 2026,
the next rollout step should be visibility on GitHub before widening
remediation behavior for non-Sonar sources.

That means:

- normalized findings should first publish into authoritative GitHub work-item
  issues
- repeated sync runs should reconcile those work items correctly
- stale-item behavior should be validated under repeated GitHub sync
- only after that should non-Sonar findings be allowed to widen the shared
  remediation boundary

Why:

- operators need to see and trust the normalized finding model before more
  automation is attached to it
- GitHub issue visibility gives a safer feedback loop than immediately enabling
  remediation from a new source
- it keeps rollout failures in publication and lifecycle projection rather than
  in code-changing automation

### 8.7 Locked Decision: One Canonical Work Item Can Preserve Multiple Sources

When multiple sources report the same underlying issue, the product should not
force source adapters to choose precedence during collection.

Instead:

- source adapters normalize findings independently
- shared reconciliation may later determine that multiple normalized findings
  describe the same underlying issue
- the product may then keep one canonical workflow item while preserving the
  contributing sources as provenance

This gives the operator one shared workflow inventory without losing the fact
that more than one source backed the same issue.

If the overlap between sources is uncertain, the product should prefer keeping
them separate rather than deduping aggressively.

### 8.8 Locked Decision: Source Identity Is Low-Emphasis in Queue Views

Source identity should be visible to operators, but it should not dominate the
main queue or workflow inventory.

The UX rule is:

- single-source items keep source identity low-emphasis in the main queue
- multi-source items show a compact indicator in the main queue
- full source provenance appears in the detail view or work-item body

This means:

- the main queue stays optimized for actionability and scanability
- multi-source reinforcement is visible when it matters
- detailed provenance remains available for trust, debugging, and traceability

Recommended wording:

- use neutral labels such as `Contributing sources`
- avoid implying one source is primary unless the product truly has that
  concept

## 9. Recommendation

The next implementation phase should treat generic finding ingestion as the new
product boundary and use one additional dogfooding source only after that
boundary exists.

That keeps the product moving toward:

- shared workflow behavior,
- source-agnostic downstream logic,
- and a clearer platform story beyond a SonarQube-first rollout.

The next rollout sequence should therefore be:

1. publish normalized findings into GitHub work-item issues
2. validate repeated sync and stale-item lifecycle behavior on GitHub
3. widen remediation only after the GitHub visibility path is trusted
