"""Bounded function-aware context selection for review files."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from zeroone_ops.services.shared.context_builder import _window_bounds


@dataclass(frozen=True)
class FunctionContextSelection:
    """Represent one selected line window for a changed file."""

    start_line: int
    end_line: int
    line_ranges: tuple[tuple[int, int], ...]


def select_function_aware_window(
    *,
    file_path: str,
    raw_content: str,
    line_count: int,
    changed_start: int,
    changed_end: int,
    fallback_start_line: int,
    fallback_end_line: int,
    enable_function_context: bool,
    max_function_context_lines: int,
) -> FunctionContextSelection:
    """Return one bounded function-aware line window when possible."""
    if (
        not enable_function_context
        or max_function_context_lines <= 0
        or not file_path.endswith(".py")
        or line_count <= 0
    ):
        return FunctionContextSelection(
            start_line=fallback_start_line,
            end_line=fallback_end_line,
            line_ranges=((fallback_start_line, fallback_end_line),),
        )

    try:
        tree = ast.parse(raw_content)
    except SyntaxError:
        return FunctionContextSelection(
            start_line=fallback_start_line,
            end_line=fallback_end_line,
            line_ranges=((fallback_start_line, fallback_end_line),),
        )

    function_bounds = _enclosing_python_function_bounds(
        tree=tree,
        changed_start=changed_start,
        changed_end=changed_end,
    )
    if function_bounds is None:
        return FunctionContextSelection(
            start_line=fallback_start_line,
            end_line=fallback_end_line,
            line_ranges=((fallback_start_line, fallback_end_line),),
        )

    function_start, function_end = function_bounds
    function_line_count = function_end - function_start + 1
    if function_line_count <= max_function_context_lines:
        return FunctionContextSelection(
            start_line=function_start,
            end_line=function_end,
            line_ranges=((function_start, function_end),),
        )

    return _clip_large_function_window(
        function_start=function_start,
        function_end=function_end,
        changed_start=changed_start,
        changed_end=changed_end,
        line_count=line_count,
        max_function_context_lines=max_function_context_lines,
    )


def _enclosing_python_function_bounds(
    *,
    tree: ast.AST,
    changed_start: int,
    changed_end: int,
) -> tuple[int, int] | None:
    """Return the nearest enclosing Python function bounds for the changed lines."""
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.lineno <= changed_start
        and (node.end_lineno or node.lineno) >= changed_end
    ]
    if not candidates:
        return None
    selected = min(candidates, key=lambda node: (node.end_lineno or node.lineno) - node.lineno)
    return selected.lineno, selected.end_lineno or selected.lineno


def _clip_large_function_window(
    *,
    function_start: int,
    function_end: int,
    changed_start: int,
    changed_end: int,
    line_count: int,
    max_function_context_lines: int,
) -> FunctionContextSelection:
    """Return one deterministic clipped function-aware slice for a large function."""
    changed_span = changed_end - changed_start + 1
    if max_function_context_lines <= 1:
        return FunctionContextSelection(
            start_line=changed_start,
            end_line=changed_end,
            line_ranges=((changed_start, changed_end),),
        )

    signature_lines = min(3, function_end - function_start + 1, max_function_context_lines - 1)
    remaining_budget = max(1, max_function_context_lines - signature_lines)
    hunk_budget = max(changed_span, remaining_budget)
    hunk_padding = max(0, hunk_budget - changed_span)
    hunk_start, hunk_end = _window_bounds(
        issue_line=changed_start,
        line_count=line_count,
        lines_before=hunk_padding // 2,
        lines_after=hunk_padding - (hunk_padding // 2),
    )
    hunk_start = max(hunk_start, function_start)
    hunk_end = min(hunk_end, function_end)

    signature_end = min(function_end, function_start + signature_lines - 1)
    line_ranges: tuple[tuple[int, int], ...]
    if hunk_start <= signature_end + 1:
        combined_end = max(signature_end, hunk_end)
        line_ranges = ((function_start, combined_end),)
    else:
        line_ranges = (
            (function_start, signature_end),
            (hunk_start, hunk_end),
        )

    return FunctionContextSelection(
        start_line=line_ranges[0][0],
        end_line=line_ranges[-1][1],
        line_ranges=line_ranges,
    )
