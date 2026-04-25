# Function-Aware Review Context Technical Design

## 1. Scope

This document defines a technical design for adding bounded function-aware
context expansion to the review workflow described in:

- [functional-design-pr-review.md](functional-design-pr-review.md)
- [functional-design-pr-review-function-aware-context.md](functional-design-pr-review-function-aware-context.md)

The goal is to improve review context quality for long Python functions without
abandoning the current deterministic hunk-window model.

## 2. Technical Objectives

- Keep the current fixed hunk-window context builder intact as the baseline.
- Detect enclosing Python function boundaries for reviewed hunks.
- Expand to enclosing-function context when it fits within a configured limit.
- Fall back safely when function-aware expansion is unavailable or too large.
- Preserve deterministic prompt rendering and testability.

## 3. Design Principles

### 3.1 Extend, Do Not Replace

The existing line-window context builder should remain the fallback and
baseline behavior.

### 3.2 Python-First

The first version should support Python only. Multi-language function-aware
parsing can come later if testing shows it is worth the complexity.

### 3.3 Bounded Context

Whole-function context should be used only when it stays within a configured
line limit or can be clipped in a deterministic way.

## 4. Current State

Today [review_context_builder.py](../src/zeroone_ops/services/review_context_builder.py)
does this:

1. parse the changed hunk line range,
2. expand it with fixed `max_context_lines_before` and
   `max_context_lines_after`,
3. render that slice as numbered snippet content.

That means the builder does not currently know or care whether the changed hunk
is inside:

- a function,
- a class,
- or top-level script/module logic.

## 5. Proposed Technical Approach

### 5.1 AST-First Python Function Boundary Detection

Add an internal helper in
[review_context_builder.py](../src/zeroone_ops/services/review_context_builder.py)
such as:

```python
def _enclosing_python_function_bounds(
    lines: list[str],
    changed_start: int,
    changed_end: int,
) -> tuple[int, int] | None:
    ...
```

Responsibilities:

- parse Python source with `ast`,
- find the nearest enclosing `FunctionDef` or `AsyncFunctionDef` containing the
  changed hunk,
- use AST node `lineno` / `end_lineno` to recover function bounds when
  available,
- return 1-based start/end lines when a reliable enclosing function is found.

If AST parsing fails or no enclosing function can be identified reliably, fall
back to the existing hunk-window behavior.

### 5.2 Window Selection Strategy

For Python files:

1. build the current fixed hunk window,
2. attempt to detect enclosing function bounds with AST,
3. if no function is found, keep the fixed window,
4. if a function is found and fits within the configured function-aware limit,
   use the enclosing function bounds,
5. if the function is too large, use a bounded function-aware slice that still
   includes:
   - the function signature,
   - the changed hunk,
   - and as much nearby code as allowed by the configured limit.

### 5.3 Config Additions

Extend review config with something like:

- `review.enable_function_context: bool = true`
- `review.max_function_context_lines: int = 200`

The existing:

- `review.max_context_lines_before`
- `review.max_context_lines_after`

should still remain relevant for:

- non-Python files,
- fallback behavior,
- and bounded clipping decisions.

## 6. Clipping Behavior For Very Large Functions

If an enclosing function exceeds the configured function context limit:

- include the function signature and opening lines,
- include the changed hunk,
- include the local trailing lines around the hunk,
- mark the resulting snippet as truncated.

The first version does not need a perfect semantic clipper. A deterministic,
bounded approximation is enough.

## 7. Suggested Module Ownership

### 7.1 `models/config.py`

Owns:

- the new review-context configuration knobs.

### 7.2 `services/review_context_builder.py`

Owns:

- Python AST parsing for enclosing function detection,
- bounded whole-function or clipped-function context selection,
- fallback to the current line-window model.

## 8. Backward Compatibility

This should be a safe additive change:

- prompt format stays the same,
- `ReviewFileContext` shape stays the same,
- only the selected `content`, `start_line`, `end_line`, and `truncated`
  values may change.

That means older tests and downstream prompt rendering should remain mostly
stable once expectations are updated.

## 9. Risks And Guardrails

### 9.1 Oversized Function Context

Guardrail:

- cap function-aware expansion with `max_function_context_lines`
- preserve truncation markers through the existing `ReviewFileContext`
  behavior

### 9.2 Incorrect Function Boundary Detection

Guardrail:

- limit first version to Python
- prefer AST-derived bounds over indentation-only heuristics
- if uncertain, fall back to the existing hunk window

### 9.3 Prompt Bloat

Guardrail:

- do not include whole files automatically
- keep the current bounded diff-centered model as the default fallback

## 10. Verification Strategy

Add or update tests for:

- changed hunk inside a small Python function -> whole function included
- changed hunk in non-Python file -> fixed window unchanged
- changed hunk in very large Python function -> bounded clipped function-aware
  slice
- ambiguous or unsupported case -> safe fallback to current line-window logic
- correct `truncated`, `start_line`, and `end_line` behavior for expanded
  context

## 11. Done When

- the review context builder can include enclosing Python function context
  deterministically,
- long-function misses are reduced on legacy repositories,
- and the prompt size remains bounded enough for repeated review use.
