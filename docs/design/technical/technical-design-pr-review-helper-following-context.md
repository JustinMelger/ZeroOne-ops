# Helper-Following Review Context Technical Design

## 1. Scope

This document defines a technical design for adding bounded helper-following
context to the review workflow described in:

- [functional-design-pr-review.md](../functional/functional-design-pr-review.md)
- [functional-design-pr-review-helper-following-context.md](../functional/functional-design-pr-review-helper-following-context.md)

The goal is to let the review bot inspect directly relevant local helpers
without introducing a full repo-exploration agent.

## 2. Technical Objectives

- Keep changed-function context as the baseline review packet.
- Detect direct helper usage inside the changed function.
- Resolve a small number of local helpers when resolution is reliable.
- Include helper snippets in the review packet within strict bounds.
- Fall back safely to the existing context-builder behavior when resolution is
  ambiguous or too large.

## 3. Design Principles

### 3.1 Bounded One-Hop Exploration

The first version should stop at directly called helpers from the changed
function. No recursive multi-hop traversal in v1.

### 3.2 Python-First

The first implementation should support Python only, using AST where possible
for changed-function detection and helper-call discovery.

### 3.3 Resolution Must Be Conservative

If symbol resolution is ambiguous, the builder should skip that helper and
continue, rather than guessing and polluting the review prompt.

### 3.4 Same-File First

The first implementation should prefer same-file direct function resolution.
Project-local imported helpers can come later once the same-file path proves
useful in testing.

## 4. Current State

Today the review context builder:

1. parses changed hunk ranges,
2. builds a local line window or function-aware slice,
3. renders that snippet as the file context for review.

It does not currently include directly used helpers outside the selected local
snippet.

## 5. Proposed Technical Approach

### 5.1 Changed Function Detection

Build on the function-aware context work:

- identify the enclosing changed Python function,
- use that as the anchor for helper-following analysis.

### 5.2 Direct Call Extraction

Within the changed function, use Python AST to collect a bounded set of direct
call expressions, such as:

- local `foo(...)`
- method or attribute calls when they can be resolved to a local helper safely

The first version should prefer confidence over coverage.
In practice, that means:

- direct same-file function calls first,
- no broad object-method following in v1 unless resolution is trivially clear.
- no test-helper or generated-code following in v1.

### 5.3 Helper Resolution

Add an internal helper in
[review_context_builder.py](../../../src/zeroone_ops/services/review/review_context_builder.py)
such as:

```python
def _resolve_direct_local_helpers(...) -> list[ResolvedHelperContext]:
    ...
```

Responsibilities:

- resolve direct local function definitions in the same file,
- optionally resolve project-local imported helpers when the import target is
  unambiguous,
- return bounded helper snippets with file path and line range.

For the first version, "resolvable" should mean:

- one clear local definition,
- no ambiguous import fan-out,
- no dynamic dispatch guesswork.

### 5.4 Bounded Supplemental Context

For each changed function:

1. identify direct helper calls,
2. resolve up to a configured maximum number of helpers,
3. include helper snippets only while within the total helper line budget,
4. attach those snippets as supplemental context in the review packet.

Recommended first limits:

- `review.max_followed_helpers_per_function: int = 3`
- `review.max_followed_helper_lines: int = 120`
- `review.max_followed_helper_lines_per_review: int = 240`
- `review.helper_follow_depth: int = 1`
- `review.enable_helper_following: bool = true`
- `review.log_helper_following: bool = false`

## 6. Suggested Data Shape

Extend the review context model with a bounded supplemental helper section,
such as:

- helper file path
- helper symbol
- helper start/end lines
- helper snippet content

This can remain separate from the primary changed-file snippet so the prompt
still distinguishes:

- changed code,
- supporting helper context.

Each helper block should include:

- helper file path
- helper symbol
- helper start/end lines
- helper snippet content

Helper ordering should remain deterministic:

- same-file helpers first,
- then imported helpers,
- then by first call occurrence in the changed function.

Helper-following should only run when the changed hunk is anchored to an
identifiable enclosing function. Otherwise the builder should keep the existing
baseline context path.

Helper-following should also respect existing review path controls such as
supported and ignored paths.

## 7. Module Ownership

### 7.1 `models/config.py`

Owns:

- helper-following feature toggle and budgets.
- helper-following diagnostics toggle.

### 7.2 `models/review.py`

Owns:

- any new structured helper-context model used in the prompt packet.

### 7.3 `services/review_context_builder.py`

Owns:

- changed-function anchoring,
- AST-based direct call extraction,
- conservative helper resolution,
- bounded supplemental helper inclusion,
- lightweight debug logging for helper-following decisions when enabled.

## 8. Backward Compatibility

This should be additive:

- the existing changed-file review packet remains valid,
- helper context is supplemental and bounded,
- when helper-following is disabled or unavailable, current behavior stays the
  same.

## 9. Risks And Guardrails

### 9.1 Wrong Helper Resolution

Guardrail:

- only follow helpers when symbol resolution is confident
- skip ambiguous cases
- start with same-file direct functions before broadening to imports

### 9.2 Unclear Skip Behavior

Guardrail:

- use a small explicit skip-reason taxonomy in diagnostics, such as:
  - `ambiguous_symbol`
  - `unsupported_call_shape`
  - `budget_exceeded`
  - `non_python`
  - `parse_failed`

### 9.3 Prompt Bloat

Guardrail:

- limit helper count
- limit helper lines
- keep one-hop depth only
- cap total helper context per merge request as well as per changed function

### 9.4 Overreach Toward Agentic Review

Guardrail:

- no arbitrary file search
- no open-ended call graph traversal
- no recursive helper following in v1

### 9.5 Logging Noise

Guardrail:

- keep helper-following diagnostics disabled by default
- emit only concise support logs, not full code snippets or prompt bodies
- keep diagnostics out of MR notes and normal operator summaries

## 10. Verification Strategy

Add or update tests for:

- changed function with direct local helper -> helper snippet included
- changed function with multiple helpers -> respect helper count budget
- same-file direct helper resolution -> preferred and deterministic
- helper ordering -> deterministic across repeated runs
- ambiguous import resolution -> helper skipped cleanly
- non-Python file -> helper-following disabled and baseline context preserved
- ignored or unsupported helper path -> helper skipped cleanly
- helper-following disabled by config -> current behavior unchanged
- helper-following diagnostics enabled -> expected support log messages emitted

## 11. Done When

- the review context builder can include bounded directly relevant helper code,
- helper-dependent false positives decrease,
- and the workflow still behaves like structured bounded review rather than
  full repo exploration.
