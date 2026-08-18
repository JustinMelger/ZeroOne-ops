# ZeroOne Ops Dashboard Operator Policy Technical Design

> **Status: Historical.** GitLab dashboard mode is deprecated compatibility
> behavior. For current issue-mode contracts, see the [design index](../README.md).

## 1. Scope

This document defines the technical design for dashboard-backed operator policy
in ZeroOne Ops.

It complements
[functional-design-dashboard-operator-policy.md](../functional/functional-design-dashboard-operator-policy.md),
which defines the operator-facing behavior and product goals.

This technical design focuses on:

- policy data models,
- dashboard-backed storage and rendering direction,
- remediation intake behavior,
- migration from config-first severity policy,
- schema versioning and live dashboard migration needs.

## 2. Architectural Direction

The dashboard should be treated as:

- the broader shared work inventory,
- the operator-facing remediation policy surface,
- the shared control plane for automated pickup decisions.

Producer bots should continue to sync normalized work items without applying
operator exclusions during sync.

The remediation bot should remain responsible for deciding automated pickup from
that synchronized inventory.

This means operator policy is remediation-owned in application, but
dashboard-backed in visibility and persistence.

## 3. Safety Boundary

Hard safety guards stay independent from operator policy.

Examples:

- rename-style issue guard,
- multi-file safety limits,
- unsupported workflow/source types,
- patch/validation/approval safety boundaries.

Operator policy may narrow what remediation will attempt. It must not widen the
built-in safety boundary.

## 4. Policy Data Model

The operator policy model should cover two independent decisions.

### 4.1 Severity Policy Record

Suggested fields:

- `severity`
- `enabled`
- `reason`
- `updated_at`
- `updated_by`

Purpose:

- replace config-only severity gating as the main operator-facing control path,
- keep severity policy visible and editable through the dashboard-backed policy
  surface.

Normalization responsibility:

- producer-side normalization should compute the automation severity band,
- the dashboard and remediation policy layers should consume normalized
  severity, not re-implement source-specific mappings,
- raw source severity may still be preserved separately for traceability.

### 4.2 Issue-Class Policy Record

Suggested fields:

- `source`
- `issue_key`
- `scope` (optional, reserved for later)
- `excluded`
- `reason`
- `updated_at`
- `updated_by`

Purpose:

- allow operators to exclude grouped issue classes from automation while
  keeping synchronized work visible.

First-version scope decision:

- the first operator-facing version should not expose scoped exclusions,
- exclusions should apply repo-wide for the grouped `source + issue_key`,
- `scope` may remain in the model for later expansion, but it should not be
  part of the first dashboard command grammar.

### 4.3 Grouped Issue Inventory Record

Recommended first grouping key:

- `source + issue_key`

Suggested derived fields per group:

- `source`
- `issue_key`
- `current_item_count`
- `severities_present` (normalized automation severity bands)
- `source_severities_present` (optional raw source severities)
- `excluded`
- `exclusion_reason`
- `last_updated`
- `sample_matches`

This grouped view is derived from synchronized dashboard work items and current
policy state.

## 5. Dashboard Rendering Model

The dashboard should evolve from flat remediation item sections into a combined
model of:

- item lifecycle sections,
- explicit policy sections,
- grouped issue inventory.

Recommended machine-owned policy sections:

1. `Automation Severity Policy`
- one row per severity,
- enabled/disabled state,
- reason when disabled,
- updated metadata.

2. `Excluded Issue Classes`
- grouped source/key rows currently excluded from automation,
- exclusion reason,
- updated metadata,
- matching item count.

3. `Issue Class Inventory`
- grouped source/key rows for policy-relevant current work,
- current item count,
- severity mix,
- excluded state,
- blocked-by-severity-only signal.

Recommended first operator-facing status language:

- `eligible for automation`
- `excluded from automation`
- `blocked by severity policy`
- `blocked by safety guard`

The first implementation should not render every grouped issue class by
default. It should prefer a narrower set such as:

- currently excluded groups,
- groups currently blocked by disabled severity policy,
- optionally the top few active groups by count.

The existing item sections should remain in place for active remediation
lifecycle tracking.

## 6. Operator Write Path

The first interactive version should not depend on free-form dashboard markdown
editing.

Preferred technical direction:

- descriptive policy state should be rendered in the dashboard for readability,
- raw checkbox edits should not be treated as the authoritative policy write
  contract,
- operators act through a bounded dashboard command or similarly strict
  interaction path,
- that interaction is parsed into a structured policy mutation,
- the policy mutation updates dashboard-backed policy state,
- the dashboard body is re-rendered from structured state.

Required supported mutations:

- enable severity,
- disable severity,
- exclude issue class,
- remove issue-class exclusion.

Recommended first transport:

- structured command comments on the dashboard issue itself,
- parsed only when they use a strict policy prefix such as `/zeroone policy`,
- ignored when they do not match the bounded command grammar.

The dashboard should include a compact machine-owned `Operator Policy Actions`
legend with:

- the exact command prefix,
- the supported command shapes,
- example commands for severity and issue-class policy,
- a note that direct markdown edits and raw checkbox changes do not mutate
  policy.

Recommended service boundary:

- `dashboard_policy_action_service` should own operator-issued policy actions,
  command validation, policy mutation application, and dashboard re-render
  triggers,
- `dashboard_reconciliation_service` should remain focused on observed workflow
  state, retry eligibility, and convergence logic,
- these responsibilities should stay separate even if they live in the same
  dashboard domain package.

The exact command transport remains open, but the mutation contract should be
strict, typed, and machine-validated.

## 7. Remediation Intake Behavior

Recommended pickup order:

1. load dashboard item,
2. apply hard built-in safety guards,
3. apply dashboard-backed severity policy,
4. apply dashboard-backed issue-class exclusions,
5. continue with normal remediation eligibility and selection.

This keeps the policy decision visible and explicit at the same boundary where
automation risk is accepted or rejected.

## 8. Canonical Persistence Direction

The dashboard should be the canonical shared policy store for operator-managed
remediation policy.

That means:

- machine-owned dashboard policy sections are the authoritative shared source of
  truth,
- remediation reads effective policy from the dashboard-backed policy model,
- local state remains secondary operational state rather than the canonical
  policy store,
- config provides bootstrap defaults at startup but is no longer the primary
  day-to-day operator control path once dashboard policy exists.

This is the practical near-term choice because the product does not yet have a
separate shared remote state layer beyond the dashboard.

As a result, schema versioning and migration are mandatory parts of the design.
Delete-and-recreate recovery is not acceptable once live policy is stored in
and read from the dashboard.

## 9. Migration Direction

The current product still carries a transition on severity policy, but
issue-class exclusion authority should now live in the dashboard-backed policy
model rather than in a separate state path.

### 9.1 Severity Migration

Current source of truth:

- `remediation.bootstrap_severities`

Target direction:

- dashboard-backed severity policy becomes the main operator-facing source of
  truth,
- config severity becomes bootstrap default or safety fallback.

Suggested migration:

1. seed dashboard severity policy from config when no dashboard policy exists,
2. render the effective seeded severity policy visibly in the dashboard so
   operators can see the active baseline,
3. make sure policy evaluation uses normalized automation severity rather than
   raw source severity,
4. once dashboard severity policy exists, remediation reads the dashboard
   policy and config severity becomes bootstrap/default input rather than the
   active operator control plane,
5. later de-emphasize config severity in operator docs and workflows.

### 9.2 Exclusion Migration

Current source of truth:

- dashboard-backed issue-class policy state.

Target direction:

- dashboard-backed issue-class policy becomes the operator-facing source of
  truth.

Suggested migration:

1. render and persist issue-class exclusions in canonical dashboard policy
   state,
2. apply that canonical dashboard policy during remediation intake,
3. remove duplicate issue-class exclusion reads so visibility and enforcement
   stay aligned.

## 10. Schema Versioning And Migration

This work should not repeat the earlier dashboard-breakage pattern where the
safe recovery was deleting and recreating the dashboard.

Required direction:

- explicit document-level dashboard schema versioning,
- tolerant parsing for additive sections where possible,
- rewrite or migration support for older live dashboard bodies.

First-version versioning decision:

- use one document-level schema version for the machine-owned dashboard
  structure,
- do not introduce section-level versioning in the first implementation,
- add section-level versions later only if real change pressure justifies the
  extra complexity.

Legacy dashboard rule:

- if the dashboard has no schema marker, treat it as legacy unversioned
  `v0`,
- attempt migration through a dedicated legacy parser when the old shape is
  recognized confidently,
- rewrite the dashboard in the current versioned format after successful
  migration,
- fail safely when the unversioned dashboard shape is too ambiguous to migrate
  reliably.

Current implementation expectation:

- recognized legacy dashboards are rewritten to the current schema during
  normal dashboard load,
- policy evaluation should happen against the rewritten canonical document
  model rather than against mixed legacy/current bodies,
- schema rewrite remains explicit product behavior, not an incidental side
  effect.

The first interactive policy rollout should not depend on delete-and-recreate
recovery for normal upgrades.

## 11. Implementation Phases

### Phase 1: Read-Only Policy View

- render severity policy and exclusion policy into the dashboard,
- add grouped issue-class inventory,
- keep current policy behavior unchanged underneath.

### Phase 2: Dashboard-Backed Policy Writes

- add bounded operator interaction for policy changes,
- persist policy changes through the dashboard-backed policy path,
- keep schema migration explicit while the policy surface evolves.

### Phase 3: Dashboard-First Policy Authority

- make dashboard-backed policy the primary operator-facing authority,
- reduce config severity to bootstrap/fallback semantics,
- remove duplicate issue-class exclusion-control paths.

## 12. Guardrails

- do not let dashboard policy weaken hard safety guards,
- do not hide synchronized work during producer sync based on operator policy,
- do not make the first operator interaction model depend on free-form markdown
  edits,
- do not treat one repository's policy as universal platform truth,
- do not require a full allowlist taxonomy to use the product well.
