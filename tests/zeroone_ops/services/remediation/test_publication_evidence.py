"""Protect operator content while replacing only marked publication evidence."""

import pytest

from zeroone_ops.models.analysis import (
    SemanticSafetyAssessment,
    ValidationCommandResult,
    ValidationResult,
)
from zeroone_ops.services.remediation.publication_evidence import (
    EVIDENCE_END,
    EVIDENCE_START,
    render_publication_evidence,
    replace_publication_evidence,
)


def test_marked_replacement_preserves_surrounding_bytes_and_is_idempotent():
    old = render_publication_evidence(commit_sha="old")
    prefix, suffix = "Operator intro\r\n\r\n", "\r\n\r\n## Operator notes\r\nKeep this é.\r\n"
    evidence = render_publication_evidence(commit_sha="new")
    expected = prefix + evidence + suffix
    assert replace_publication_evidence(prefix + old + suffix, evidence) == expected
    assert replace_publication_evidence(expected, evidence) == expected
    assert "Published commit: `new`" in expected
    assert "Validation evidence unavailable" in expected


def test_legacy_description_is_preserved_and_only_one_latest_block_is_added():
    original = "## Validation\nOperator-added details\n## Semantic Safety\nOld explanation.\n"
    first = replace_publication_evidence(original, render_publication_evidence(commit_sha="first"))
    second = replace_publication_evidence(first, render_publication_evidence(commit_sha="second"))
    assert first.endswith(original)
    assert second.endswith(original)
    assert second.count(EVIDENCE_START) == 1
    assert "Published commit: `first`" not in second
    assert "Supersedes earlier validation and rationale" in second


@pytest.mark.parametrize(
    "description",
    [
        EVIDENCE_START,
        EVIDENCE_END,
        EVIDENCE_END + "\n" + EVIDENCE_START,
        EVIDENCE_START + "\n" + EVIDENCE_START + "\n" + EVIDENCE_END,
        "<!-- zeroone:publication-evidence:broken -->",
        "<!-- ZEROONE:publication-evidence:start -->\n" + EVIDENCE_END,
        "inline " + EVIDENCE_START + "\n" + EVIDENCE_END,
        EVIDENCE_START + "\n" + EVIDENCE_END + " trailing text",
    ],
)
def test_ambiguous_or_damaged_markers_are_not_overwritten(description):
    with pytest.raises(ValueError):
        replace_publication_evidence(description, render_publication_evidence(commit_sha="new"))


def test_external_evidence_cannot_terminate_the_owned_block_or_render_html():
    injected = f"value `{EVIDENCE_END}`\n<script>bad</script>"
    evidence = render_publication_evidence(
        commit_sha="new",
        validation_result=ValidationResult(
            passed=True,
            results=[
                ValidationCommandResult(
                    command=injected,
                    exit_code=0,
                    stdout="secret output",
                    stderr="",
                    duration_ms=1,
                )
            ],
            summary="secret summary",
        ),
        semantic_safety=SemanticSafetyAssessment(
            current_behavior=injected,
            intended_behavior=injected,
            preservation_evidence=[injected],
        ),
    )
    assert evidence.count(EVIDENCE_END) == 1
    assert "<script>" not in evidence
    assert "secret" not in evidence
    assert replace_publication_evidence("Operator note", evidence).endswith("Operator note")


def test_generated_evidence_requires_exactly_one_complete_owned_block():
    with pytest.raises(ValueError):
        replace_publication_evidence("original", "not managed evidence")


def test_command_operators_remain_readable_without_rendering_literal_html_entities():
    command = 'python -c "print(1 < 2)" && uv run pytest'
    evidence = render_publication_evidence(
        validation_result=ValidationResult(
            passed=True,
            results=[
                ValidationCommandResult(
                    command=command,
                    exit_code=0,
                    stdout="",
                    stderr="",
                    duration_ms=1,
                )
            ],
            summary="Passed",
        )
    )
    assert '<code>python -c "print(1 &lt; 2)" &amp;&amp; uv run pytest</code>' in evidence
    assert "`python" not in evidence
