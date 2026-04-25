# Functional Design: Stable Finding Identity For PR Review Reconciliation

## Purpose

Make repeated PR review follow-up matching more stable by separating:

- machine-facing finding identity used for reconciliation
- human-facing wording used in merge request notes

The current implementation reconciles follow-up findings mostly from persisted
`file_path: title` summaries, with conservative title-overlap fallback when
wording drifts. That is acceptable during testing, but it still ties matching
too closely to presentation text.

## Problem

Repeated reviews on the same merge request can describe the same underlying
issue with slightly different wording:

- `Unconditional exception breaks vehicle detail retrieval`
- `Unconditional exception makes vehicle detail lookup always fail`

When persisted review state stores only human-facing summaries, reconciliation
must infer sameness from wording overlap. That can miss real continuity or make
matching logic more heuristic-heavy than desired.

## Goal

Introduce a stable stored finding identity so the review workflow can:

- match the same concern across repeated passes without depending on title drift
- keep follow-up notes conversational and trust-building
- reduce false `new` classifications for the same underlying issue
- keep matching deterministic and review-state driven

## Non-Goals

- no large semantic matching system
- no global cross-MR or cross-repository finding identity
- no replacement of human-facing titles in MR notes
- no requirement to migrate all old persisted review state before rollout

## User-Facing Outcome

Operators should experience repeated review notes like a continued thread:

- same issue still present -> `still appears unresolved`
- earlier issue gone -> `no longer appears present`
- different issue -> `new issue`

That continuity should keep working even when the human-facing finding title
changes a bit between review passes.

## Functional Requirements

### 1. Stable persisted identity

Each persisted prior review finding should store:

- machine identity for reconciliation
- human summary for note rendering and operator context
- severity as already stored today

### 2. Deterministic identity shape

The first version should use a bounded deterministic identity derived from the
current review finding, not an opaque model-generated id.

The identity should be stable enough to survive small wording drift while still
remaining conservative.

### 3. Matching precedence

Follow-up reconciliation should prefer:

1. exact stable identity match
2. legacy summary/title fallback for older persisted review entries

This keeps backward compatibility while moving the steady-state behavior onto a
more stable machine-facing format.

### 4. Backward compatibility

Existing persisted review state without a stable identity must continue to work.

The workflow should:

- use stable identity when available
- fall back to legacy summary-based matching otherwise
- avoid forcing manual state cleanup during rollout

### 5. Human wording remains separate

MR notes should still use:

- readable titles
- conversational follow-up phrasing
- operator-friendly summaries

The stable identity is for matching, not presentation.

## First-Version Identity Direction

The first version should stay conservative and derive identity from bounded
structured finding properties, such as:

- file path
- normalized issue subject derived from the title

For the first implementation:

- identity should be app-derived, not model-provided
- identity should be stored as one canonical string
- evidence and explanation text should not be part of the first identity shape
- human-facing summaries should still use the earlier stored title when follow-up
  notes describe an unresolved or resolved earlier concern

The exact normalization approach belongs in the technical design, but the core
functional rule is:

- canonical stored identity for machines
- human title for notes

## Risks

### False same-issue match

If identity is too broad, different concerns in the same file may be treated as
the same issue.

### Backward drift

If rollout does not preserve legacy fallback behavior, follow-up continuity
could degrade for already-persisted review history.

### Identity collision

If identity normalization is too broad, two different concerns in the same file
could collapse to the same stored identity.

The first version should avoid that by keeping normalization deliberately
conservative rather than trying to repair collisions with extra counters or
suffixes immediately.

## Acceptance Criteria

This design is successful when:

- repeated review matching depends primarily on stored machine identity instead
  of title wording
- old persisted review state still reconciles safely through fallback behavior
- follow-up notes remain readable and conversational
- testing shows fewer missed same-issue matches caused by wording drift
