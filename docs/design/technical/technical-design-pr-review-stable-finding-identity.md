# Technical Design: Stable Finding Identity For PR Review Reconciliation

## Scope

Introduce a canonical stored finding identity for repeated PR review
reconciliation while preserving:

- current review output schema
- current MR note format
- backward-compatible matching for older persisted review state

## Current State

Persisted prior review findings are currently stored as:

- `summary`
- `severity`

The summary is usually a human-facing string shaped like:

- `path/to/file.py: Finding title`

Follow-up reconciliation then matches current findings to prior findings using:

- exact `(file_path, title, normalized summary)` matching first
- conservative same-file title-overlap fallback

This works, but it makes machine matching depend too much on note wording.

## Target State

Persisted prior review findings should store both:

- `identity`
- `summary`

Where:

- `identity` is canonical machine-facing reconciliation data
- `summary` remains the operator-facing human reference

## Proposed Data Model Change

Extend persisted prior review finding state with a new optional field:

- `identity: str | None`

Suggested first-version meaning:

- canonical normalized finding key

Persisted state remains backward compatible because legacy entries can omit the
field.

## Identity Construction

The first version should keep identity deterministic and conservative.

Recommended shape:

- `<normalized_file_path>::<normalized_issue_subject>`

Where:

- `normalized_file_path` comes from `finding.file_path`
- `normalized_issue_subject` comes from a bounded normalization of the finding
  title

The normalization should stay lightweight and explainable, for example:

- lowercase
- collapse whitespace
- tokenize title text
- lightly normalize stable suffix drift
- drop very low-signal tokens if needed

This is intentionally simpler than semantic or embedding-based matching.

Decisions for the first version:

- store identity as one canonical string rather than multiple persisted fields
- derive identity in application code only
- do not include evidence or explanation text in the first identity
- keep normalization stronger than displayed title wording, but still
  conservative enough to avoid broad same-file collisions

## Persistence Path

When a review result is marked reviewed:

1. build prior review finding state from current structured findings
2. store:
   - `identity`
   - `summary`
   - `severity`

This affects:

- review-state persistence
- prior-review loading

## Reconciliation Path

When reconciling current findings against the latest prior pass:

1. if prior finding has `identity`, match on exact identity first
2. if identity is absent, fall back to current legacy summary matching
3. keep current ambiguity guardrails

This means the title-overlap fallback becomes legacy support, not the primary
steady-state mechanism.

For new persisted entries:

- do not continue using fuzzy title-overlap matching once identity is present
- use exact identity matching as the primary and preferred path
- reserve the legacy fallback for older persisted review history without
  identity

## Rendering Boundaries

The review publisher should continue to render follow-up wording from human
summaries, not from canonical identity strings.

The split stays:

- identity -> matching
- summary/title -> note wording

## Backward Compatibility

Required rollout behavior:

- old persisted entries without identity continue to reconcile
- new entries always write identity
- no migration is required to begin rollout

The first rollout should not backfill identity while loading old state. Writing
identity for new persisted entries is sufficient to begin the transition.

Optional later cleanup:

- once older review history naturally ages out, simplify the reconciliation
  path by reducing the legacy fallback surface

## Test Plan

Add or update tests for:

1. persisted prior review finding state includes identity
2. loaded prior review context preserves identity when present
3. reconciliation prefers exact identity over title-overlap fallback
4. legacy entries without identity still reconcile through fallback logic
5. wording drift in later passes still reconciles correctly through stable
   identity

## Risks

### Identity too broad

If identity normalization is too coarse, unrelated findings in the same file
may collide.

Mitigation:

- keep identity conservative
- prefer exact deterministic identity over fuzzy semantic expansion

### Identity too narrow

If identity normalization mirrors human title wording too closely, the change
will not improve stability much.

Mitigation:

- normalize the subject more strongly than the displayed title
- keep fallback tests based on real wording drift examples

## Implementation Slices

Recommended order:

1. extend persisted prior-review finding state with optional `identity`
2. write identity during review-state persistence
3. load identity into prior review context
4. update reconciliation to prefer identity matching
5. keep legacy fallback for old entries
6. validate on repeated live review sequences before removing any legacy path
