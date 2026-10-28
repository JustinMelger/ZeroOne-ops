"""Build bounded command feedback without granting additional edit scope."""

from zeroone_ops.models.analysis import ValidationCommandFeedback, ValidationFeedback
from zeroone_ops.models.validation_evidence import ValidationAssessment
from zeroone_ops.services.remediation.validation_feedback.failure_evidence import (
    failure_excerpt,
    sanitize_validation_text,
)

_MAX_FAILURES = 10
_MAX_CHARACTERS = 4_000


class ValidationFeedbackBuilder:
    """Translate an independent correction decision into untrusted prompt evidence."""

    def build(
        self,
        *,
        assessment: ValidationAssessment,
        files_touched: list[str],
    ) -> ValidationFeedback | None:
        """Decline correction if essential failure evidence cannot fit the bounded packet."""
        if not assessment.correction.eligible:
            return None
        paths = sorted(set(files_touched))
        remaining = _MAX_CHARACTERS - len(", ".join(paths)) - 200
        failures: list[ValidationCommandFeedback] = []
        comparison = assessment.comparison
        for index in assessment.correction.command_indices[:_MAX_FAILURES]:
            result = comparison.post_edit.results[index]
            command = sanitize_validation_text(result.command).replace("\n", " ")
            overhead = len(command) + 150
            if remaining <= overhead:
                break
            output = "\n".join(
                value.strip() for value in (result.stdout, result.stderr) if value.strip()
            )
            introduced = assessment.commands[index].new_diagnostics
            if introduced:
                output = "\n".join(
                    f"{d.file_path}:{d.line}: {d.severity}: {d.message} [{d.code}]"
                    for d in introduced
                )
            excerpt = failure_excerpt(output, "")
            if not excerpt:
                continue
            if len(excerpt) > remaining - overhead:
                break
            failures.append(
                ValidationCommandFeedback(
                    command=command,
                    exit_code=result.exit_code,
                    baseline_exit_code=comparison.baseline.results[index].exit_code,
                    excerpt=excerpt,
                )
            )
            remaining -= overhead + len(excerpt)
        if not failures:
            return None
        return ValidationFeedback(
            allowed_file_paths=paths,
            failures=failures,
            omitted_failure_count=len(assessment.correction.command_indices) - len(failures),
        )
