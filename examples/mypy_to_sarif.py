#!/usr/bin/env python3
"""Convert Mypy's newline-delimited JSON diagnostics into SARIF 2.1.0."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_arguments() -> argparse.Namespace:
    """Return the input and output paths supplied on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Mypy JSON output file")
    parser.add_argument("output", type=Path, help="SARIF output file")
    return parser.parse_args()


def load_diagnostics(input_path: Path) -> list[dict[str, Any]]:
    """Read the newline-delimited JSON diagnostics produced by Mypy."""
    diagnostics: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        input_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            diagnostic = json.loads(line)
        except json.JSONDecodeError as error:
            message = f"Invalid Mypy JSON on line {line_number}: {error.msg}"
            raise ValueError(message) from error
        if not isinstance(diagnostic, dict):
            raise ValueError(f"Invalid Mypy JSON on line {line_number}: expected an object")
        diagnostics.append(diagnostic)
    return diagnostics


def make_result(diagnostic: dict[str, Any]) -> dict[str, Any]:
    """Map one Mypy diagnostic to its SARIF result representation."""
    result: dict[str, Any] = {
        "ruleId": diagnostic.get("code") or "mypy",
        "level": {"error": "error", "warning": "warning", "note": "note"}.get(
            diagnostic.get("severity"),
            "error",
        ),
        "message": {"text": diagnostic.get("message", "Mypy diagnostic")},
    }
    filename = diagnostic.get("file")
    if filename:
        region: dict[str, int] = {"startLine": diagnostic.get("line") or 1}
        if diagnostic.get("column") is not None:
            region["startColumn"] = diagnostic["column"] + 1
        if diagnostic.get("end_line") is not None:
            region["endLine"] = diagnostic["end_line"]
        if diagnostic.get("end_column") is not None:
            region["endColumn"] = diagnostic["end_column"] + 1
        result["locations"] = [
            {"physicalLocation": {"artifactLocation": {"uri": filename}, "region": region}}
        ]
    return result


def convert(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a SARIF document from Mypy diagnostics."""
    rule_ids = sorted({diagnostic.get("code") or "mypy" for diagnostic in diagnostics})
    rules = [{"id": rule_id, "name": rule_id} for rule_id in rule_ids]
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Mypy",
                        "informationUri": "https://mypy-lang.org/",
                        "rules": rules,
                    }
                },
                "results": [make_result(diagnostic) for diagnostic in diagnostics],
            }
        ],
    }


def main() -> None:
    """Convert a Mypy JSON output file to SARIF."""
    arguments = parse_arguments()
    sarif = convert(load_diagnostics(arguments.input))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(sarif, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
