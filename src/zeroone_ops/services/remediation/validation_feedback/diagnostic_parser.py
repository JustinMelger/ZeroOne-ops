"""Parse only supported MyPy/Ruff console contracts, without discarding unknown output."""

import re
import shlex
from pathlib import PurePosixPath
from typing import Literal

from zeroone_ops.models.analysis import ValidationCommandResult
from zeroone_ops.models.validation_evidence import ParsedValidationOutput, ToolDiagnostic

_MYPY = re.compile(r"^(.+?):(\d+)(?::(\d+))?: (error|warning|note): (.*?)(?:  \[([^\]]+)\])?$")
_RUFF_CODE = r"(?:[A-Z]+\d+|invalid-syntax)"
_RUFF = re.compile(rf"^(.+?):(\d+):(\d+): ({_RUFF_CODE}) (?:\[\*\] )?(.*)$")
_RUFF_HEADER = re.compile(rf"^({_RUFF_CODE}) (?:\[\*\] )?(.+)$")
_RUFF_LOCATION = re.compile(r"^\s*--> (.+?):(\d+):(\d+)\s*$")
_SUMMARY = {
    "mypy": re.compile(
        r"^(?:Found \d+ errors? in \d+ files? \(checked \d+ source files?\)|"
        r"Success: no issues found in \d+ source files?)$"
    ),
    "ruff": re.compile(
        r"^(?:All checks passed!|Found \d+ errors?(?: \(\d+ fixed, \d+ remaining\))?\.|"
        r"\[\*\] \d+ fixable with (?:the )?`--fix`(?: option)?\.?|"
        r"No fixes available \(\d+ hidden fixes can be enabled with "
        r"the `--unsafe-fixes` option\)\.)$"
    ),
}


def validation_tool(command: str) -> Literal["mypy", "ruff"] | None:
    """Recognize supported diagnostic contracts; other commands require clean validation."""
    tokens = _command_tokens(command)
    if not tokens:
        return None
    executable = PurePosixPath(tokens[0]).name
    if executable == "mypy":
        return "mypy"
    if executable == "ruff" and tokens[1:2] == ["check"]:
        return "ruff"
    return None


def validation_executable(command: str) -> str | None:
    """Recognize executable exit contracts independently of diagnostic parsing."""
    tokens = _command_tokens(command)
    return PurePosixPath(tokens[0]).name if tokens else None


def _command_tokens(command: str) -> list[str]:
    """Unwrap bounded invocations, refusing shell composition or changed directory semantics."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    if any(character in command for character in "|;&><`\n$"):
        return []
    if tokens and PurePosixPath(tokens[0]).name == "env":
        tokens = tokens[1:]
        while tokens and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*=.*", tokens[0]):
            tokens = tokens[1:]
        if tokens[:1] == ["--"]:
            tokens = tokens[1:]
        if not tokens or tokens[0].startswith("-"):
            return []
    if len(tokens) >= 2 and PurePosixPath(tokens[0]).name == "uv" and tokens[1] == "run":
        tokens = _uv_command(tokens[2:])
    if len(tokens) >= 3 and re.fullmatch(r"python(?:3(?:\.\d+)?)?", PurePosixPath(tokens[0]).name):
        if tokens[1] == "-m":
            tokens = tokens[2:]
    return tokens


def _uv_command(tokens: list[str]) -> list[str]:
    """Unwrap known uv flags without mistaking option values for the executable."""
    switches = {
        "--no-sync",
        "--active",
        "--frozen",
        "--locked",
        "--offline",
        "--isolated",
        "--no-project",
        "--no-default-groups",
        "--all-groups",
        "--no-dev",
        "--dev",
        "--all-extras",
        "--quiet",
        "-q",
        "--verbose",
        "-v",
    }
    valued = {
        "--group",
        "--no-group",
        "--package",
        "--python",
        "--extra",
        "--with",
    }
    position = 0
    while position < len(tokens) and tokens[position].startswith("-"):
        option = tokens[position]
        if option == "--":
            return tokens[position + 1 :]
        if option in switches:
            position += 1
        elif option.partition("=")[0] in valued:
            position += 1 if "=" in option else 2
        else:
            return []
    return tokens[position:]


def execution_failure(result: ValidationCommandResult) -> bool:
    """Operational exits cannot authorize publication, even when repeated verbatim."""
    return (
        result.exit_code < 0
        or result.exit_code in {124, 126, 127}
        or result.exit_code >= 128
        or (
            validation_executable(result.command) in {"mypy", "ruff"}
            and result.exit_code not in {0, 1}
        )
        or (result.exit_code != 0 and _startup_failure(result))
    )


def _startup_failure(result: ValidationCommandResult) -> bool:
    """Recognize operational evidence without treating traceback caller paths as policy."""
    output = f"{result.stdout}\n{result.stderr}"
    return (
        any(
            marker in result.stderr.lower() for marker in ("command not found", "permission denied")
        )
        or re.search(r"(?im)^(?:.*: )?No module named ['\"]?(?:pytest|mypy|ruff)\b", output)
        is not None
        or re.search(
            r"(?im)^(?:error: )?(?:unable to access jarfile|failed to (?:fetch|download|resolve) "
            r"(?:package|dependencies|https?://)|authentication failed|unauthorized access)",
            output,
        )
        is not None
    )


def parse_validation_output(result: ValidationCommandResult) -> ParsedValidationOutput:
    """Parse all nonblank output; unexpected lines make the evidence unusable."""
    tool = validation_tool(result.command)
    if tool is None:
        return ParsedValidationOutput(tool=None)

    diagnostics: list[ToolDiagnostic] = []
    summary_counts: list[int] = []
    pending: tuple[str, str] | None = None
    frame = False
    fix_context = False
    for output in (result.stdout, result.stderr):
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _SUMMARY[tool].fullmatch(line):
                count = _summary_count(line)
                if count is not None:
                    summary_counts.append(count)
                continue
            match = (_MYPY if tool == "mypy" else _RUFF).fullmatch(line)
            if match:
                path, row, column, kind, message = match.group(1, 2, 3, 4, 5)
                code = match.group(6) if tool == "mypy" else kind
                if kind != "note":
                    diagnostics.append(
                        ToolDiagnostic(
                            PurePosixPath(path).as_posix(),
                            int(row),
                            int(column) if column else None,
                            kind if tool == "mypy" else "error",
                            code,
                            message,
                        )
                    )
                continue
            if tool == "mypy" and re.fullmatch(r".+?: note: .+", line):
                continue
            if tool == "ruff":
                header = _RUFF_HEADER.fullmatch(line)
                location = _RUFF_LOCATION.fullmatch(raw_line)
                if header and pending is None:
                    pending = (header[1], header[2])
                    frame = False
                    fix_context = False
                    continue
                if location and pending is not None:
                    diagnostics.append(
                        ToolDiagnostic(
                            PurePosixPath(location[1]).as_posix(),
                            int(location[2]),
                            int(location[3]),
                            "error",
                            pending[0],
                            pending[1],
                        )
                    )
                    pending = None
                    frame = True
                    continue
                if frame and line.startswith("help: "):
                    fix_context = True
                    continue
                if frame and re.fullmatch(r"(?:\d+\s*\|.*|\|.*)", line):
                    continue
                if fix_context and re.fullmatch(r"(?:\d+\s*)?[+-](?: .*|$)", line):
                    continue
            return ParsedValidationOutput(
                tool=tool, recognized=False, failure_kind="unsupported_format"
            )

    consistent = pending is None and all(
        d.line > 0 and (d.column is None or d.column > 0) for d in diagnostics
    )
    consistent = consistent and ((result.exit_code == 0) == (not diagnostics))
    consistent = consistent and all(count == len(diagnostics) for count in summary_counts)
    return ParsedValidationOutput(
        tool,
        tuple(diagnostics),
        consistent,
        failure_kind=None if consistent else "contradictory",
    )


def _summary_count(line: str) -> int | None:
    """Validate error totals, but never mistake fixability hints for diagnostic counts."""
    if line.startswith(("Success:", "All checks passed!")):
        return 0
    remaining = re.search(r"\(\d+ fixed, (\d+) remaining\)", line)
    if remaining:
        return int(remaining[1])
    found = re.match(r"Found (\d+) errors?", line)
    return int(found[1]) if found else None
