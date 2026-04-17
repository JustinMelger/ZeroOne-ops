# Technical Design: Structured PR Review Reconciliation

## Scope

Introduce stronger structured review and prior-review fields to support more
stable repeated-review reconciliation while preserving:

- app-owned canonical identity
- backward-compatible prior review loading
- existing trust guardrails for ambiguity and resolution claims

## Current State

Today the review workflow uses:

- prior review context with bounded summaries and optional stored identity
- app-derived canonical identity from normalized file path and title subject
- follow-up reconciliation in the review publisher

This is a good intermediate state, but repeated-review matching still depends
partly on:

- human wording drift
- app heuristics around title normalization

## Target State

Later, the workflow should support:

1. richer structured prior review context
2. model-provided structured finding fields
3. app-derived canonical reconciliation key from those fields

## Proposed Model Direction

### Prior review finding state

Persisted prior review findings should later be able to carry structured fields
in addition to:

- `identity`
- `summary`
- `severity`

Likely additions:

- `symbol`
- `issue_kind`
- optional `region_hint`

### Current review finding result

The review model should later be able to return bounded identity-relevant
fields, such as:

- `symbol`
- `issue_kind`
- optional `region_hint`

The app should validate and normalize those fields before deriving the final
canonical identity.

## Identity Ownership Rule

The model must not own the final key string.

Preferred flow:

1. model returns structured finding fields
2. app validates and normalizes those fields
3. app derives canonical identity
4. app persists identity and any structured supporting fields

This keeps key evolution centralized and deterministic.

## Reconciliation Direction

The later reconciliation order should become:

1. exact canonical identity
2. structured field comparison when needed
3. legacy fallback for older state

The current title-overlap and summary fallback should shrink over time as
structured state becomes more common.

## Suggested First Structured Fields

Recommended first set:

- `file_path`
- `symbol`
- `issue_kind`
- optional `region_hint`

Recommended exclusions for the first version:

- severity in the identity
- full evidence text in the identity
- opaque model-generated key strings

## Backward Compatibility

The structured rollout should preserve:

- older persisted entries with no structured fields
- newer entries with identity only
- later entries with identity plus structured fields

That means reconciliation needs to remain layered for a while:

- identity-first for new entries
- structured comparison where available
- legacy fallback otherwise

## Testing Strategy

Future tests should cover:

1. model-provided structured fields round-trip through validation
2. app-derived canonical identity from structured fields
3. repeated same-issue sequences with title drift but stable structured fields
4. mixed old/new review history
5. ambiguity handling when structured fields disagree or are incomplete

## Risks

### Schema churn

If the structured finding model grows too quickly, prompt stability and review
validation may become harder to maintain.

### False certainty from structured fields

Structured fields can still be wrong. App-side validation and trust guardrails
must remain in place.

## Implementation Direction

A reasonable later rollout would be:

1. define bounded structured finding fields in the review schema
2. extend prior review state to persist those fields
3. include structured prior review fields in prompt context
4. derive app-owned canonical identity from structured fields
5. prefer structured reconciliation over wording-based fallback
