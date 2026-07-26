"""Source-local SARIF ingestion into the shared finding contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import unquote

from zeroone_ops.models.finding import (
    FindingCollectionMetadata,
    FindingCollectionResult,
    FindingSourceMetadata,
    NormalizedFinding,
    RemediationContext,
)
from zeroone_ops.utils.finding_identity import (
    build_fallback_finding_identity,
    normalize_identity_text,
)

JsonDict = dict[str, object]
_SARIF_FALLBACK_IDENTITY_CATEGORY = "lint_fix"


class SarifFindingSource:
    """Collect SARIF findings behind the shared ingestion contract."""

    def __init__(self, repo_root: Path | None = None) -> None:
        """Initialize the SARIF source with the repository root for path normalization."""
        self.repo_root = (repo_root or Path.cwd()).resolve()

    def collect_artifact_findings(
        self,
        artifact_path: Path,
        *,
        declared_source_id: str | None = None,
    ) -> FindingCollectionResult:
        """Collect normalized findings from one SARIF artifact file."""
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Expected top-level SARIF object.")
        findings: list[NormalizedFinding] = []
        warnings: list[str] = []
        skipped_count = 0
        artifact_source_ids: set[str] = set()
        source_completeness: dict[str, bool] = {}
        fallback_source_id = declared_source_id or _artifact_fallback_source_id(artifact_path)
        runs = payload.get("runs", [])
        empty_runs = isinstance(runs, list) and not runs

        if not isinstance(runs, list):
            warnings.append("Skipped SARIF runs with unexpected non-list shape.")
            skipped_count += 1
        else:
            for run in runs:
                if not isinstance(run, dict):
                    warnings.append("Skipped SARIF run with unexpected non-object shape.")
                    skipped_count += 1
                    continue
                (
                    findings_for_run,
                    warnings_for_run,
                    skipped_for_run,
                    source_id,
                    is_complete,
                ) = _collect_run_findings(run, repo_root=self.repo_root)
                warnings.extend(warnings_for_run)
                skipped_count += skipped_for_run
                if declared_source_id is not None and source_id != declared_source_id:
                    skipped_count += max(1, len(findings_for_run))
                    warnings.append(
                        "Skipped SARIF run because its tool source "
                        f"{source_id!r} does not match declared source "
                        f"{declared_source_id!r}."
                    )
                    continue
                findings.extend(findings_for_run)
                artifact_source_ids.add(source_id)
                source_completeness[source_id] = (
                    source_completeness.get(source_id, True) and is_complete
                )

        return FindingCollectionResult(
            findings=findings,
            metadata=FindingCollectionMetadata(
                source_id=_artifact_source_id(
                    artifact_source_ids,
                    fallback_source_id=fallback_source_id,
                ),
                artifact_reference=str(artifact_path),
                managed_source_ids=sorted(
                    [
                        source_id
                        for source_id, is_complete in source_completeness.items()
                        if is_complete
                    ]
                    or ({fallback_source_id} if empty_runs else set())
                ),
                warnings=warnings,
                statistics={
                    "collected": len(findings),
                    "skipped": skipped_count,
                },
            ),
        )


def _collect_run_findings(
    run: JsonDict,
    *,
    repo_root: Path,
) -> tuple[list[NormalizedFinding], list[str], int, str, bool]:
    """Normalize one SARIF run into findings plus bounded warnings."""
    driver = _dict_value(_dict_value(run, "tool"), "driver")
    tool_name = _string_or_none(driver.get("name"))
    source_id = _sarif_source_id(tool_name)
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
        finding = _normalize_result(
            result=result,
            rule_index=rule_index,
            tool_name=tool_name,
            source_id=source_id,
            repo_root=repo_root,
        )
        if finding is None:
            skipped_count += 1
            rule_id = result.get("ruleId") or "<unknown-rule>"
            warnings.append(
                f"Skipped SARIF result {rule_id} because no repository-relative path was found."
            )
            continue
        findings.append(finding)
    return findings, warnings, skipped_count, source_id, skipped_count == 0


def _normalize_result(
    *,
    result: JsonDict,
    rule_index: dict[str, JsonDict],
    tool_name: str | None,
    source_id: str,
    repo_root: Path,
) -> NormalizedFinding | None:
    """Normalize one SARIF result into the shared finding contract."""
    repository_path = _repository_path_from_result(result, repo_root=repo_root)
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
    region_hint = _region_hint(result)
    native_id = _native_result_id(result)
    finding_id = _finding_identity(
        result=result,
        repository_path=repository_path,
        title=title,
        summary=summary,
        diagnostic_code=rule_id,
        region_hint=region_hint,
    )
    level = _string_or_none(result.get("level"))

    return NormalizedFinding(
        finding_id=finding_id,
        source_id=source_id,
        severity=_normalize_sarif_level(level),
        title=title,
        summary=summary,
        repository_path=repository_path,
        line_start=line_start,
        line_end=line_end,
        region_hint=region_hint,
        remediation_context=RemediationContext(
            category="static_analysis_fix",
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


def _repository_path_from_result(result: JsonDict, *, repo_root: Path) -> str | None:
    """Return the repository-relative SARIF artifact path when available."""
    location = _first_location(result)
    uri = _dict_value(_dict_value(location, "physicalLocation"), "artifactLocation").get("uri")
    if not isinstance(uri, str) or not uri.strip():
        return None
    normalized = uri.strip()
    if normalized.startswith("file://"):
        return _repository_relative_file_uri_path(normalized, repo_root=repo_root)
    if normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = unquote(normalized)
    path = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or any(part == ".." for part in path.parts):
        return None
    return str(path) or None


def _repository_relative_file_uri_path(uri: str, *, repo_root: Path) -> str | None:
    """Return one repo-relative path from a file URI when it resolves inside the repo."""
    normalized = unquote(uri[len("file://") :])
    candidate = Path(normalized)
    try:
        resolved_candidate = candidate.resolve()
    except OSError:
        return None
    if resolved_candidate != repo_root and repo_root not in resolved_candidate.parents:
        return None
    return resolved_candidate.relative_to(repo_root).as_posix()


def _artifact_source_id(source_ids: set[str], *, fallback_source_id: str) -> str:
    """Return the collection-level source id for one SARIF artifact."""
    if not source_ids:
        return fallback_source_id
    if len(source_ids) == 1:
        return next(iter(source_ids))
    return "sarif"


def _artifact_fallback_source_id(artifact_path: Path) -> str:
    """Return a stable artifact-scoped fallback source id for empty SARIF artifacts."""
    return _sarif_source_id(artifact_path.stem)


def _sarif_source_id(tool_name: str | None) -> str:
    """Return a bounded stable source id derived from SARIF tool identity."""
    if tool_name is None:
        return "sarif"
    parts = [character.lower() if character.isalnum() else "-" for character in tool_name.strip()]
    slug = "".join(parts).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return f"{slug or 'sarif'}-sarif"


def _region_from_result(result: JsonDict) -> JsonDict:
    """Return the first SARIF physical region object when present."""
    return _dict_value(_dict_value(_first_location(result), "physicalLocation"), "region")


def _line_range_from_result(result: JsonDict) -> tuple[int | None, int | None]:
    """Return the optional normalized line range for one SARIF result."""
    region = _region_from_result(result)
    start_line = region.get("startLine")
    end_line = region.get("endLine")
    return (
        start_line if isinstance(start_line, int) else None,
        end_line if isinstance(end_line, int) else None,
    )


def _region_hint(result: JsonDict) -> str | None:
    """Return a bounded region hint for fallback finding identity."""
    region = _region_from_result(result)
    start_line = region.get("startLine")
    end_line = region.get("endLine")
    start_column = region.get("startColumn")
    end_column = region.get("endColumn")
    normalized_start_line = start_line if isinstance(start_line, int) else None
    normalized_end_line = end_line if isinstance(end_line, int) else None
    normalized_start_column = start_column if isinstance(start_column, int) else None
    normalized_end_column = end_column if isinstance(end_column, int) else None

    if normalized_start_line is None:
        return None
    if normalized_start_column is None:
        return _line_region_hint(
            line_start=normalized_start_line,
            line_end=normalized_end_line,
        )
    effective_end_line = normalized_end_line or normalized_start_line
    if effective_end_line == normalized_start_line and (
        normalized_end_column is None or normalized_end_column == normalized_start_column
    ):
        return f"line-{normalized_start_line}-col-{normalized_start_column}"
    end_column_value = normalized_end_column or normalized_start_column
    return (
        f"lines-{normalized_start_line}-{effective_end_line}"
        f"-cols-{normalized_start_column}-{end_column_value}"
    )


def _line_region_hint(*, line_start: int | None, line_end: int | None) -> str | None:
    """Return a bounded line-only region hint for fallback finding identity."""
    if line_start is None:
        return None
    if line_end is None or line_end == line_start:
        return f"line-{line_start}"
    return f"lines-{line_start}-{line_end}"


def _finding_identity(
    *,
    result: JsonDict,
    repository_path: str,
    title: str,
    summary: str,
    diagnostic_code: str | None,
    region_hint: str | None,
) -> str:
    """Return the stable shared identity for one SARIF result."""
    fingerprint_identity = _fingerprint_identity(
        result,
        repository_path=repository_path,
        diagnostic_code=diagnostic_code,
        region_hint=region_hint,
    )
    if fingerprint_identity is not None:
        return fingerprint_identity

    base_identity = build_fallback_finding_identity(
        repository_path=repository_path,
        title=title,
        summary=summary,
        # Keep the established identity component while remediation uses the neutral category.
        category=_SARIF_FALLBACK_IDENTITY_CATEGORY,
        diagnostic_code=diagnostic_code,
        region_hint=region_hint,
    )
    result_key = normalize_identity_text(summary)
    if result_key == "unknown":
        result_key = normalize_identity_text(title)
    if result_key == "unknown":
        return base_identity
    return f"{base_identity}::{result_key}"


def _native_result_id(result: JsonDict) -> str | None:
    """Return the best bounded source-local fingerprint when available."""
    fingerprints = _string_pairs(result.get("fingerprints", {}))
    if fingerprints:
        if len(fingerprints) == 1:
            return fingerprints[0][1]
        key, value = fingerprints[0]
        return f"{key}={value}"
    partial_fingerprints = _string_pairs(result.get("partialFingerprints", {}))
    if partial_fingerprints:
        if len(partial_fingerprints) == 1:
            return partial_fingerprints[0][1]
        key, value = partial_fingerprints[0]
        return f"{key}={value}"
    return None


def _fingerprint_identity(
    result: JsonDict,
    *,
    repository_path: str,
    diagnostic_code: str | None,
    region_hint: str | None,
) -> str | None:
    """Return an order-independent stable identity from SARIF fingerprints."""
    context_pairs = [
        ("path", repository_path),
        ("rule", diagnostic_code or ""),
        ("region", region_hint or ""),
    ]
    fingerprints = _string_pairs(result.get("fingerprints", {}))
    if fingerprints:
        return _stable_fingerprint_identity("fingerprints", fingerprints + context_pairs)
    partial_fingerprints = _string_pairs(result.get("partialFingerprints", {}))
    if partial_fingerprints:
        return _stable_fingerprint_identity(
            "partial-fingerprints",
            partial_fingerprints + context_pairs,
        )
    return None


def _string_pairs(value: object) -> list[tuple[str, str]]:
    """Return sorted string key/value pairs from one fingerprint object."""
    if not isinstance(value, dict):
        return []
    pairs = [
        (key, entry)
        for key, entry in value.items()
        if isinstance(key, str) and isinstance(entry, str) and entry
    ]
    return sorted(pairs)


def _stable_fingerprint_identity(prefix: str, pairs: list[tuple[str, str]]) -> str:
    """Return a bounded order-independent identity for fingerprint pairs."""
    payload = "|".join(f"{key}={value}" for key, value in pairs)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


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
    normalized = (level or "warning").lower()
    if normalized == "error":
        return "high"
    if normalized == "warning":
        return "medium"
    return "low"
