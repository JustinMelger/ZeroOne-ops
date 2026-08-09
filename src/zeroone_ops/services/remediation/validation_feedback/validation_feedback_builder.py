"""Build bounded validator feedback for one remediation correction attempt."""

from __future__ import annotations

from zeroone_ops.models.analysis import (
    ValidationComparison,
    ValidationDiagnostic,
    ValidationFeedback,
)

_MAX_DIAGNOSTICS = 10
_MAX_CHARACTERS = 4_000


class ValidationFeedbackBuilder:
    """Translate an actionable comparison into safe prompt context."""

    def build(
        self,
        *,
        comparison: ValidationComparison,
        files_touched: list[str],
    ) -> ValidationFeedback | None:
        """Return bounded feedback only for an edited-file regression."""
        if comparison.outcome != "actionable_regression":
            return None
        allowed_file_paths = sorted(set(files_touched))
        diagnostics: list[ValidationDiagnostic] = []
        for diagnostic in comparison.new_relevant_diagnostics:
            if len(diagnostics) >= _MAX_DIAGNOSTICS:
                break
            remaining = _MAX_CHARACTERS - _rendered_length(
                allowed_file_paths=allowed_file_paths,
                diagnostics=diagnostics,
            )
            if remaining <= 0:
                break
            prefix_length = len(f"\n- `{diagnostic.file_path}` via `{diagnostic.command}`: ")
            if remaining <= prefix_length:
                break
            diagnostics.append(
                diagnostic.model_copy(
                    update={"excerpt": diagnostic.excerpt[: remaining - prefix_length]}
                )
            )
        return ValidationFeedback(
            allowed_file_paths=allowed_file_paths,
            diagnostics=diagnostics,
        )


def _rendered_length(
    *,
    allowed_file_paths: list[str],
    diagnostics: list[ValidationDiagnostic],
) -> int:
    """Return the exact prompt-section length for the current feedback packet."""
    lines = [
        "Allowed files: " + ", ".join(f"`{path}`" for path in allowed_file_paths),
        "New diagnostics:",
        *[
            f"- `{diagnostic.file_path}` via `{diagnostic.command}`: {diagnostic.excerpt}"
            for diagnostic in diagnostics
        ],
    ]
    return len("\n".join(lines))
