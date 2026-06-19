# Review Package Layout

## Purpose

This design gives Phase `2b` a concrete package-boundary target before source
files or tests are moved.

The goal is not broad repository refactoring. The goal is to stop the review
workflow from continuing to grow across a flat `services/review/` namespace
now that GitHub review support is active and Phase `3` would otherwise add more
files on top of the current spread.

## Scope

This design is intentionally limited to the review workflow:

- review intake
- review context building
- candidate and precision orchestration
- continuity and prior-comment handling
- publication and finalization
- provider review seams
- review-state persistence helpers that belong to the review domain

It does not attempt to redesign:

- remediation packaging
- dashboard packaging
- shared Git provider abstractions outside review

## Current Problem

The current review implementation is structurally correct, but review-domain
code is still spread across one broad package:

- `services/review/change_request_intake.py`
- `services/review/review_context_builder.py`
- `services/review/review_prior_comment_loader.py`
- `services/review/review_publisher.py`
- `services/review/review_runner.py`
- and many adjacent review-stage helpers

That flat layout now has a few downsides:

- provider work touches many unrelated files at once
- continuity and publication concerns are harder to isolate mentally
- review integration tests do not have a clean source map to mirror
- later GitHub inline-comment work would likely widen the spread again

## Design Goals

- keep provider-neutral review meaning in the review domain
- keep provider-specific transport in provider-local modules
- group related review responsibilities together
- make future test mirroring straightforward
- avoid over-abstracting beyond current product needs

## Non-Goals

- no attempt to create a generic multi-domain platform package
- no forced convergence of dashboard and review packaging
- no large rename wave outside the review workflow

## Target Layout

The review domain should move from one flat package toward a small number of
clear subpackages.

### 1. `services/review/intake/`

Owns selecting the current change request and validating review-entry
preconditions.

Target contents:

- `change_request_intake.py`
- `change_request_selector.py`

Responsibility:

- CI/runtime change-request targeting
- already-reviewed revision gating
- provider-head vs triggering-head validation

### 2. `services/review/context/`

Owns deterministic local review context construction.

Target contents:

- `review_context_builder.py`
- `review_function_context.py`
- `review_helper_context.py`

Responsibility:

- changed-file filtering
- local file windowing
- helper/context expansion
- repository-guidance attachment

### 3. `services/review/continuity/`

Owns prior-review recovery, same-SHA reuse, overlap analysis, and inline
continuity support.

Target contents:

- `review_prior_comment_loader.py`
- `review_prior_comment_parser.py`
- `review_overlap_packet_builder.py`
- `review_overlap_analysis_service.py`
- `review_overlap_reconciliation.py`
- `review_inline_comment_continuity_service.py`

Responsibility:

- prior-summary lookup
- machine-safe payload parsing
- overlap candidate construction
- inline-comment continuity decisions

### 4. `services/review/publish/`

Owns human/machine review output publication and finalization.

Target contents:

- `review_publisher.py`
- `review_finalization_service.py`
- `review_dashboard_updater.py`

Responsibility:

- authoritative summary comment rendering and publication
- inline comment publication
- provider warnings
- dashboard mirror side effects

### 5. `services/review/pipeline/`

Owns staged review orchestration and artifact assembly.

Target contents:

- `review_runner.py`
- `review_candidate_generation_service.py`
- `review_reconciliation_service.py`
- `review_artifact_builder.py`
- `review_artifact_validator.py`
- `review_reconciled_decision_builder.py`

Responsibility:

- stage ordering
- candidate/precision orchestration
- artifact validation
- run-level diagnostics and state transitions

### 6. `services/review/state/`

Owns review-specific state mutation helpers.

Target contents:

- `review_state_service.py`

Responsibility:

- review run start/finish/failure bookkeeping
- same-SHA reuse persistence
- reviewed revision state updates

### 7. `providers/review/`

Provider review transport should eventually live under a review-focused provider
 namespace instead of a flat providers directory.

Target contents:

- `providers/review/platform.py`
- `providers/review/gitlab.py`
- `providers/review/github.py`

Responsibility:

- provider review transport contracts
- provider-specific review clients

Important boundary:

- this design only covers review transport
- it does not imply moving dashboard or generic GitLab API clients into the same
  package right now

## Migration Rules

Phase `2b` should follow these rules while moving files:

1. move by responsibility group, not alphabetically
2. keep public imports stable only where they are needed for a short migration
   window
3. do not create compatibility aliases that survive beyond the cleanup slice
4. update tests only after the source/package target for that responsibility is
   stable

## Test Mirroring Rule

Once the source layout above is in place, the review test tree should mirror it:

- `tests/zeroone_ops/services/review/intake/`
- `tests/zeroone_ops/services/review/context/`
- `tests/zeroone_ops/services/review/continuity/`
- `tests/zeroone_ops/services/review/publish/`
- `tests/zeroone_ops/services/review/pipeline/`
- `tests/zeroone_ops/services/review/state/`
- `tests/zeroone_ops/providers/review/`

The current large review integration runner tests should then be split by review
workflow concerns against that package map, not before.

## Recommended Order

Recommended Phase `2b` order:

1. review config neutralization
2. review package-boundary cleanup in source
3. review provider package cleanup
4. test-tree mirroring to the stabilized source map
5. Phase `3` GitHub inline-comment work

## Why This Order

- config cleanup makes the public contract more honest
- package cleanup reduces architectural drift before more GitHub review work
- test mirroring becomes a one-time move instead of a temporary split
- Phase `3` then grows on top of a sharper review domain layout
