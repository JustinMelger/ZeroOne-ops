"""Select bounded, sanitized failure evidence without deciding repair scope."""

import re

_SENSITIVE_KEY = (
    r"(?:access[_-]?token|private[_-]?token|token|password|passwd|api[_-]?key|key|secret|"
    r"credentials?|client[_-]?secret|signature|sig|auth|x-amz-signature|x-amz-security-token)"
)
_EXCEPTION = re.compile(r"^(?:E\s+)?[\w.]*(?:Error|Exception|Interrupt|Exit)(?::|$)")
_DIAGNOSTIC = re.compile(r"^.+:\d+(?::\d+)?:\s*(?:error|warning|[A-Z]+\d+)\b")
_LOCATION = re.compile(
    r"^(?:E\s+)?(?:File [\"'].*[\"'], line \d+(?:, in .*)?|[^\s]+:\d+(?::\d+)?(?:: in .*)?)$"
)


def sanitize_validation_text(value: str) -> str:
    """Redact recognizable credentials before any evidence is selected or truncated."""
    value = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", value)
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", value)
    value = re.sub(
        r"(?s)-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)",
        "[REDACTED]",
        value,
    )
    value = re.sub(r"(?i)(https?://)[^/\s@]+@", r"\1[REDACTED]@", value)
    value = re.sub(r"(?im)((?:proxy-)?authorization\s*[:=]\s*).*$", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 [REDACTED]", value)
    value = re.sub(rf"(?i)([?&]{_SENSITIVE_KEY}=)[^&\s\"']+", r"\1[REDACTED]", value)
    value = re.sub(
        rf"(?i)(--?{_SENSITIVE_KEY}(?:=|\s+))(?:\"[^\"]*\"|'[^']*'|[^\s]+)",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(
        rf"(?i)([\"']?{_SENSITIVE_KEY}[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)",
        r"\1[REDACTED]",
        value,
    )
    return re.sub(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|glpat-[A-Za-z0-9_-]+|sk-[A-Za-z0-9_-]{12,})",
        "[REDACTED]",
        value,
    )


def failure_excerpt(stdout: str, stderr: str) -> str | None:
    """Keep exceptions before presentation headers, capped at twenty lines and 2,000 characters."""
    output = sanitize_validation_text("\n".join((stdout, stderr)))
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    candidates = [
        (index, line.strip()) for index, line in enumerate(lines) if not _source_or_locals(line)
    ]
    if not candidates:
        return None
    meaningful = [(index, line) for index, line in candidates if _priority(line) < 2]
    selection = meaningful if meaningful else candidates[-20:]
    ordered = sorted(selection, key=lambda entry: (_priority(entry[1]), -entry[0]))
    selected: dict[int, str] = {}
    remaining = 1_920
    truncated = False
    for index, line in ordered:
        if len(selected) >= 19 or remaining <= 1:
            break
        selected[index] = line[: remaining - 1]
        truncated = truncated or len(line) > len(selected[index])
        remaining -= len(selected[index]) + 1
    if not selected:
        return None
    excerpt = "\n".join(selected[index] for index in sorted(selected))
    omitted = len(lines) - len(selected)
    if omitted or truncated:
        excerpt += f"\n... output excerpted; {omitted} lines omitted."
        if truncated:
            excerpt += " Long line truncated."
    return excerpt


def _priority(line: str) -> int:
    if _EXCEPTION.match(line) or _DIAGNOSTIC.match(line) or re.match(r"^(?:FAILED|ERROR) \S", line):
        return 0
    if _LOCATION.match(line) or "ERROR collecting " in line:
        return 1
    return 2


def _source_or_locals(line: str) -> bool:
    """Exclude source displays and locals, not exception or location evidence."""
    text = line.strip()
    if _priority(text) < 2:
        return False
    return (
        text.startswith((">", "E ", "E\t", "|", "help: "))
        or re.match(r"^\d+\s*[|+-]", text) is not None
        or re.match(r"^\w+\s*=", text) is not None
        or (len(line) - len(line.lstrip()) >= 4)
    )
