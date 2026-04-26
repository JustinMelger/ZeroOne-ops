# ZeroOne Ops Dashboard Operator Policy Functional Design

## 1. Purpose

Define the product behavior for finishing the remediation operator-filter story
in ZeroOne Ops.

The dashboard should evolve from a mostly rendered status board into the main
operator-facing policy surface for remediation pickup. Operators should be able
to understand what work exists, what automation is currently allowed to pick
up, and which issue classes are intentionally excluded from automation.

## 2. Goals

- make the dashboard the main operator-facing remediation policy surface,
- keep the dashboard as the broader shared work inventory rather than a hidden
  autofix queue,
- let operators enable or disable remediation by severity,
- let operators exclude and later re-include grouped issue classes from
  automation,
- keep automation policy visible and inspectable in the same surface as the
  work inventory,
- preserve hard built-in safety guards outside operator control.

## 3. Non-Goals

- replacing hard safety guards with operator-configurable policy,
- turning free-form dashboard text into the main machine contract,
- redesigning merge-request review behavior,
- building a provider-specific custom UI before the GitLab-backed product flow
  is proven,
- solving cross-repository policy management.

## 4. Current Product Gap

Today the operator-filter story is split across several places:

- remediation severity gating still lives mainly in config,
- issue-class exclusions exist outside the dashboard interaction surface,
- the dashboard shows work, but operators cannot directly select or deselect
  issue classes for automation there.

This means the dashboard looks like a control plane without yet functioning as
one.

## 5. Primary User Stories

### 5.1 Severity Control

As an operator, I want to see whether `low`, `medium`, and `high` severity
items are currently enabled for remediation, so I can understand the current
automation boundary for this repository.

As an operator, I want to enable or disable a severity level with a reason, so
I can widen or narrow the current rollout safely without editing config by
hand.

### 5.2 Issue-Class Exclusion Control

As an operator, I want to see grouped issue classes such as
`sonarqube / python:S3776`, so I can recognize noisy or currently unsuitable
classes of work quickly.

As an operator, I want to exclude or re-include one grouped issue class from
automation, so the remediation bot stops wasting effort on known bad-fit issue
classes while the underlying work still remains visible.

### 5.3 Inventory Visibility

As an operator, I want the dashboard to show both:

- what work currently exists,
- what policy is suppressing automation pickup,

so I can distinguish missing work from intentionally skipped automation.

## 6. Product Model

The dashboard should serve three roles at once:

1. shared work inventory,
2. operator-facing remediation policy surface,
3. automation control plane for remediation pickup.

Producer bots should continue to sync normalized work items broadly.
They should not hide work based on operator exclusion choices.

The remediation bot should continue to decide what it will actually pick up,
but it should do so using policy that is visible and operator-managed through
the dashboard product surface.

## 7. Policy Concepts

The product should expose two policy layers.

### 7.1 Severity Policy

Severity policy controls whether remediation is currently allowed to attempt:

- `low`
- `medium`
- `high`

This policy should operate on normalized automation severity bands, not on raw
source-native severity labels.

Expected operator behavior:

- operators can inspect current severity policy,
- operators can enable a severity,
- operators can disable a severity with a short reason,
- dashboard views should make clear when work exists but is blocked only by
  severity policy.

### 7.2 Issue-Class Policy

Issue-class policy controls whether remediation should skip a grouped class of
work even when the severity is enabled.

Expected first grouping model:

- `source + issue_key`

Examples:

- `sonarqube / python:S3776`
- `pipeline_failure / mypy:arg-type`

Expected operator behavior:

- operators can inspect whether a grouped issue class is currently excluded,
- operators can exclude a grouped issue class with a short reason,
- operators can remove an exclusion later,
- dashboard views should show how many current items match that grouped class.

First-version scope decision:

- exclusions apply repo-wide for a grouped `source + issue_key`,
- operator-facing scope is not supported in the first version,
- the first dashboard policy workflow should not require path-specific
  exclusion targeting.

## 8. Required Dashboard Views

The dashboard should add explicit policy-oriented views in addition to the
existing item lifecycle sections.

### 8.1 Automation Severity Policy

This view should show:

- each severity,
- whether it is enabled,
- reason when disabled,
- last updated information.

### 8.2 Excluded Issue Classes

This view should show:

- grouped source/key rows currently excluded from automation,
- exclusion reason,
- current matching item count,
- last updated information.

### 8.3 Issue Class Inventory

The first grouped inventory view should stay intentionally narrow so the
dashboard does not become noisy.

The first version should focus on policy-relevant grouped issue classes, such
as:

- issue classes currently excluded from automation,
- issue classes currently blocked by disabled severity policy,
- optionally the top few active grouped issue classes by current item count.

For each shown group, the dashboard should include:

- source + issue key,
- current matching item count,
- current severities present,
- whether the class is excluded,
- whether the class is currently blocked only by severity policy.

The grouped inventory should help operators make policy decisions without
having to scan all individual items first, but it should not attempt to show
every possible issue-key grouping in the first version.

When useful, the dashboard may still surface raw source severity secondarily for
traceability, but policy status should be driven by normalized automation
severity.

## 9. Operator Actions

The first interactive version should support bounded actions, not free-form
editing.

Checkbox-style state is useful for presentation, but raw checkbox edits should
not be the authoritative policy mutation path. The dashboard may show
checkbox-like enabled/excluded state visually, while actual operator changes
should still go through a bounded structured interaction that the bot validates
and then re-renders.

Required actions:

- enable severity,
- disable severity,
- exclude issue class,
- remove issue-class exclusion,
- inspect current policy state.

Examples of intended actions:

- enable `high`
- disable `high` because rollout is not ready for broad refactors
- exclude `sonarqube / python:S3776`
- remove exclusion for `sonarqube / python:S3776`

The exact command transport can be decided later, but the product behavior must
remain structured, bounded, and machine-validated.

The dashboard should also include a compact operator action legend so the
workflow is discoverable in the product surface itself.

That legend should include:

- the exact action prefix,
- the supported command shapes,
- 2-4 short examples,
- a note that direct markdown edits do not change policy.

## 10. Pickup Semantics

The remediation bot should only pick an item when:

- the item passes hard built-in safety guards,
- the item's severity is currently enabled,
- the item's grouped issue class is not currently excluded,
- the item otherwise remains eligible for remediation.

The dashboard should make these distinctions visible enough that operators can
understand why current work is not being picked up.

Recommended first status language:

- `eligible for automation`
- `excluded from automation`
- `blocked by severity policy`
- `blocked by safety guard`

## 11. Product Guardrails

- operators may narrow automation scope, but not widen hard safety boundaries,
- excluded work remains visible in the dashboard inventory,
- producers do not silently hide work because of operator policy,
- the first interactive model should not require raw markdown editing,
- one repository's dashboard policy should not become global product truth.

## 12. Rollout Direction

Recommended rollout sequence:

### Phase 1: Read-Only Policy Visibility

- show current severity policy in the dashboard,
- show current excluded issue classes in the dashboard,
- show grouped issue-class inventory,
- keep current policy storage/behavior in place underneath.

### Phase 2: Bounded Dashboard Policy Actions

- add safe operator actions for severity enable/disable,
- add safe operator actions for issue-class exclude/unexclude,
- make the dashboard product surface the main operator workflow for policy
  changes.

### Phase 3: Dashboard-First Policy Authority

- make dashboard-backed policy the primary operator-facing control surface,
- reduce config-only severity control to bootstrap or fallback semantics,
- reduce duplicate policy editing paths once rollout is stable.
