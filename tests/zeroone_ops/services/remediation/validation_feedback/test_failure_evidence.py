"""Operator evidence is useful, bounded, and sanitized before it is retained."""

import pytest

from zeroone_ops.services.remediation.validation_feedback.failure_evidence import (
    failure_excerpt,
    sanitize_validation_text,
)


@pytest.mark.parametrize(
    "text, secret",
    [
        ("Authorization: Bearer supersecret", "supersecret"),
        ("Proxy-Authorization: Basic supersecret", "supersecret"),
        ("Bearer supersecret", "supersecret"),
        ("https://operator:supersecret@registry.example/simple", "supersecret"),
        ("https://registry.example/simple?token=supersecret&version=2", "supersecret"),
        ("https://host/file?X-Amz-Signature=supersecret", "supersecret"),
        ("pytest --api-key supersecret", "supersecret"),
        ("pytest --password='super secret'", "super secret"),
        ('{"password": "supersecret"}', "supersecret"),
        ("token=supersecret", "supersecret"),
        ("ghp_supersecrettokenvalue", "ghp_supersecrettokenvalue"),
        ("github_pat_supersecrettokenvalue", "github_pat_supersecrettokenvalue"),
        ("glpat-supersecrettokenvalue", "glpat-supersecrettokenvalue"),
        ("sk-supersecrettokenvalue", "sk-supersecrettokenvalue"),
        (
            "-----BEGIN RSA PRIVATE KEY-----\nsupersecret\n-----END RSA PRIVATE KEY-----",
            "supersecret",
        ),
    ],
)
def test_known_credentials_are_redacted_before_truncation(text, secret):
    sanitized = sanitize_validation_text(text)
    assert secret not in sanitized
    assert "[REDACTED]" in sanitized
    assert secret not in (failure_excerpt(text, "") or "")


def test_exception_is_not_lost_after_long_pytest_headers_or_unrelated_stderr():
    output = "\n".join([f"session header {index}" for index in range(100)])
    output += (
        "\n_______ ERROR collecting tests/test_api.py _______\n"
        "tests/test_api.py:5: in <module>\n"
        "    from app import value\n"
        "src/app.py:3: in <module>\n"
        "    value: MissingType = 1\n"
        "E   NameError: name 'MissingType' is not defined\n"
        "ERROR tests/test_api.py - NameError: name 'MissingType' is not defined\n"
    )
    excerpt = failure_excerpt(output, "Unrelated warning on stderr")
    assert "NameError" in excerpt
    assert "src/app.py:3" in excerpt
    assert "ERROR collecting tests/test_api.py" in excerpt
    assert "session header" not in excerpt
    assert "from app import value" not in excerpt
    assert "value: MissingType = 1" not in excerpt
    assert "omitted" in excerpt


def test_large_and_multiple_failures_preserve_exception_within_both_budgets():
    output = "\n".join(f"src/file{index}.py:{index + 1}: error: failure" for index in range(100))
    output += "\nE   TypeError: " + "x" * 4_000
    excerpt = failure_excerpt(output, "")
    assert "TypeError" in excerpt
    assert len(excerpt) <= 2_000
    assert len(excerpt.splitlines()) <= 20
    assert "omitted" in excerpt


def test_generic_failure_uses_tail_and_omits_local_variables():
    output = "\n".join(f"diagnostic header {index}" for index in range(100))
    output += "\n    local_token = sensitivevalue\nfinal failure\n"
    excerpt = failure_excerpt(output, "")
    assert "final failure" in excerpt
    assert "diagnostic header 0\n" not in excerpt
    assert "sensitivevalue" not in excerpt
    assert len(excerpt.splitlines()) <= 20


def test_terminal_control_sequences_are_removed():
    output = "\x1b[31mTypeError: failed\x1b[0m\x00\x07"
    assert sanitize_validation_text(output) == "TypeError: failed"


def test_standard_traceback_preserves_file_location_without_source_or_locals():
    excerpt = failure_excerpt(
        'Traceback (most recent call last):\n  File "src/app.py", line 3, in demo\n'
        '    return invalid.value\n    session = "private local value"\n'
        "AttributeError: missing value\n",
        "",
    )
    assert 'File "src/app.py", line 3, in demo' in excerpt
    assert "AttributeError: missing value" in excerpt
    assert "private local value" not in excerpt
    assert "return invalid.value" not in excerpt


def test_empty_evidence_is_absent():
    assert failure_excerpt(" \n", "") is None
