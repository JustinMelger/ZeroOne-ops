"""Source-local SARIF ingestion into the shared finding contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from zeroone_ops.models.finding import (
    FindingCollectionMetadata,
    FindingCollectionResult,
    FindingSourceMetadata,
    NormalizedFinding,
    RemediationContext,
)
from zeroone_ops.utils.finding_identity import build_fallback_finding_identity

JsonDict = dict[str, object]


class SarifFindingSource:
    """Collect SARIF findings behind the shared ingestion contract."""

    def collect_artifact_findings(self, artifact_path: Path) -> FindingCollectionResult:
        """Collect normalized findings from one SARIF artifact file."""
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Expected top-level SARIF object.")
        findings: list[NormalizedFinding] = []
        warnings: list[str] = []
        skipped_count = 0

        for run in payload.get("runs", []):
            if not isinstance(run, dict):
                warnings.append("Skipped SARIF run with unexpected non-object shape.")
                skipped_count += 1
                continue
            findings_for_run, warnings_for_run, skipped_for_run = _collect_run_findings(run)
            findings.extend(findings_for_run)
            warnings.extend(warnings_for_run)
            skipped_count += skipped_for_run

        return FindingCollectionResult(
            findings=findings,
            metadata=FindingCollectionMetadata(
                source_id="ruff-sarif",
                artifact_reference=str(artifact_path),
                warnings=warnings,
                statistics={
                    "collected": len(findings),
                    "skipped": skipped_count,
                },
            ),
        )


def _collect_run_findings(run: JsonDict) -> tuple[list[NormalizedFinding], list[str], int]:
    """Normalize one SARIF run into findings plus bounded warnings."""
    driver = _dict_value(_dict_value(run, "tool"), "driver")
    tool_name = _string_or_none(driver.get("name"))
    rule_index: dict[str, JsonDict] = {
        str(rule.get("id")): rule
        for rule in _list_value(driver.get("rules"))
        if isinstance(rule, dict) and rule.get("id") is not None
    }
    findings: list[NormalizedFinding] = []
    warnings: list[str] = []
    skipped_count = 0

    for result in _list_value(run.get("results")):
        if not isinstance(result, dict):
            skipped_count += 1
            warnings.append("Skipped SARIF result with unexpected non-object shape.")
            continue
        finding = _normalize_result(result=result, rule_index=rule_index, tool_name=tool_name)
        if finding is None:
            skipped_count += 1
            rule_id = result.get("ruleId") or "<unknown-rule>"
            warnings.append(
                f"Skipped SARIF result {rule_id} because no repository-relative path was found."
            )
            continue
        findings.append(finding)
    return findings, warnings, skipped_count


def _normalize_result(
    *,
    result: JsonDict,
    rule_index: dict[str, JsonDict],
    tool_name: str | None,
) -> NormalizedFinding | None:
    """Normalize one SARIF result into the shared finding contract."""
    repository_path = _repository_path_from_result(result)
    if repository_path is None:
        return None

    rule_id = _string_or_none(result.get("ruleId"))
    rule: JsonDict = rule_index.get(rule_id, {}) if rule_id is not None else {}
    title = (
        _nested_text(rule.get("shortDescription"))
        or _nested_text(rule.get("fullDescription"))
        or rule_id
        or "SARIF finding"
    )
    summary = _nested_text(result.get("message")) or title
    line_start, line_end = _line_range_from_result(result)
    region_hint = _region_hint(line_start=line_start, line_end=line_end)
    finding_id = build_fallback_finding_identity(
        repository_path=repository_path,
        title=title,
        summary=summary,
        category="lint_fix",
        diagnostic_code=rule_id,
        region_hint=region_hint,
    )
    native_id = _native_result_id(result)
    level = _string_or_none(result.get("level"))

    return NormalizedFinding(
        finding_id=finding_id,
        source_id="ruff-sarif",
        severity=_normalize_sarif_level(level),
        title=title,
        summary=summary,
        repository_path=repository_path,
        line_start=line_start,
        line_end=line_end,
        region_hint=region_hint,
        remediation_context=RemediationContext(
            category="lint_fix",
            diagnostic_code=rule_id,
        ),
        source_metadata=FindingSourceMetadata(
            native_id=native_id,
            source_url=_string_or_none(rule.get("helpUri")),
            attributes={
                "tool": tool_name,
                "rule_id": rule_id,
                "level": level,
                "rule_name": _string_or_none(rule.get("name")),
                "fingerprints": result.get("fingerprints", {}),
                "partial_fingerprints": result.get("partialFingerprints", {}),
            },
        ),
    )


def _repository_path_from_result(result: JsonDict) -> str | None:
    """Return the repository-relative SARIF artifact path when available."""
    location = _first_location(result)
    uri = _dict_value(_dict_value(location, "physicalLocation"), "artifactLocation").get("uri")
    if not isinstance(uri, str) or not uri.strip():
        return None
    normalized = uri.strip()
    if normalized.startswith("file://"):
        normalized = normalized[len("file://") :]
    normalized = normalized.lstrip("./")
    if normalized.startswith("/"):
        return None
    return normalized or None


def _line_range_from_result(result: JsonDict) -> tuple[int | None, int | None]:
    """Return the optional normalized line range for one SARIF result."""
    region = _dict_value(_dict_value(_first_location(result), "physicalLocation"), "region")
    start_line = region.get("startLine")
    end_line = region.get("endLine")
    return (
        start_line if isinstance(start_line, int) else None,
        end_line if isinstance(end_line, int) else None,
    )


def _region_hint(*, line_start: int | None, line_end: int | None) -> str | None:
    """Return a bounded region hint for fallback finding identity."""
    if line_start is None:
        return None
    if line_end is None or line_end == line_start:
        return f"line-{line_start}"
    return f"lines-{line_start}-{line_end}"


def _native_result_id(result: JsonDict) -> str | None:
    """Return the best bounded source-local fingerprint when available."""
    fingerprints = result.get("fingerprints", {})
    if isinstance(fingerprints, dict):
        for value in fingerprints.values():
            if isinstance(value, str) and value:
                return value
    partial_fingerprints = result.get("partialFingerprints", {})
    if isinstance(partial_fingerprints, dict):
        for value in partial_fingerprints.values():
            if isinstance(value, str) and value:
                return value
    return None


def _first_location(result: JsonDict) -> JsonDict:
    """Return the first SARIF location object when present."""
    locations = result.get("locations", [])
    if isinstance(locations, list) and locations and isinstance(locations[0], dict):
        return locations[0]
    return {}


def _dict_value(value: object, key: str) -> JsonDict:
    """Return one nested JSON object value when present, else an empty object."""
    if not isinstance(value, dict):
        return {}
    nested = value.get(key)
    if isinstance(nested, dict):
        return nested
    return {}


def _list_value(value: object) -> list[object]:
    """Return one JSON list value when present, else an empty list."""
    if isinstance(value, list):
        return value
    return []


def _nested_text(value: object) -> str | None:
    """Return nested SARIF text fields in their simple string form."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str) and text:
            return text
    return None


def _string_or_none(value: object) -> str | None:
    """Return a string value or ``None`` when not present."""
    if isinstance(value, str) and value:
        return value
    return None


def _normalize_sarif_level(level: str | None) -> Literal["low", "medium", "high"]:
    """Map SARIF result levels into normalized workflow severities."""
    normalized = (level or "note").lower()
    if normalized == "error":
        return "high"
    if normalized == "warning":
        return "medium"
    return "low"
