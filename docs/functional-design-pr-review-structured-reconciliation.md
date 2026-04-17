# Functional Design: Structured PR Review Reconciliation

## Purpose

Improve repeated PR review continuity by moving more of the review and
reconciliation surface onto structured machine-friendly fields instead of
deriving sameness mainly from human titles and summaries.

The current design already improved follow-up behavior through:

- bounded prior review memory
- conversational follow-up wording
- stable stored finding identity derived by the app

This follow-up design goes one step further:

- prior review context should become more explicitly structured
- the review model should return bounded structured finding identity fields
- the app should still own the final canonical reconciliation key

## Problem

Real repeated-review sequences still show title drift and wording drift such as:

- `breaks vehicle detail retrieval`
- `makes vehicle detail lookup always fail`

Those concern the same underlying bug, but app-derived title normalization can
still miss some cases or require heuristic growth over time.

## Goal

Introduce a stronger structured contract for repeated review reconciliation so:

- the model describes findings in bounded machine-friendly fields
- the app derives the final canonical key from those fields
- prior review context is easier for the model to compare against
- follow-up notes remain human-friendly and conversational

## Non-Goals

- no opaque model-provided key string as the source of truth
- no global cross-repository finding identity
- no removal of app-side ambiguity and trust guardrails
- no immediate migration away from legacy fallback behavior

## Desired Outcome

Repeated review sequences should feel more like:

- earlier concern still unresolved
- earlier concern no longer appears present
- new concern now appears

even when human-facing wording changes across passes.

## Functional Direction

### 1. Structured prior review context

Prior review context should later include more than:

- summary
- severity
- classification

It should also carry bounded structured fields that make same-issue comparison
clearer for the model and the app.

### 2. Structured finding identity fields from the model

The review model should later provide bounded structured identity-relevant
fields, such as:

- `file_path`
- `symbol` or function name
- `issue_kind`
- optional `line` or region hint

These should describe the concern in machine-friendly terms, but the app should
still compute the final canonical reconciliation identity.

### 3. App-owned final key

The canonical persisted key should remain application-owned.

That means:

- the model proposes structured fields
- the app validates and normalizes them
- the app stores the final reconciliation key

This keeps matching deterministic and easier to evolve.

### 4. Human wording remains separate

MR notes should still use human-readable wording for:

- findings
- follow-up summaries
- resolved/unresolved conversational lines

Structured identity should improve matching, not replace note wording.

## First Structured Fields Direction

The first structured fields should stay bounded and conservative.

Recommended early shape:

- `file_path`
- `symbol`
- `issue_kind`
- optional `region_hint`

And explicitly not:

- severity as part of identity
- free-form opaque finding key from the model

## Risks

### Model field drift

If the model produces unstable structured fields, matching quality may still
drift.

### Over-structuring too early

If the first field set is too large, the review response becomes harder to
stabilize and validate.

## Acceptance Criteria

This design is successful when:

- repeated same-issue matching depends less on title wording drift
- structured prior review context gives the model clearer continuity
- the app still owns the canonical reconciliation identity
- follow-up notes stay human-friendly and trust-building
