"""JSON helpers for remediation solution artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from zeroone_ops.utils.files import ensure_parent


class SupportsModelDump(Protocol):
    """Minimal protocol for Pydantic-style artifact payloads."""

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        """Serialize the object into JSON-compatible data."""


def write_solution_artifact(
    path: Path,
    *,
    issue_key: str,
    analysis: SupportsModelDump | None = None,
    structured_edit: SupportsModelDump | None = None,
    patch: SupportsModelDump | None = None,
    decision: str | None = None,
    rejection_reason: str | None = None,
    clear_patch: bool = False,
) -> None:
    """Write one remediation solution artifact file."""
    ensure_parent(path)
    payload = _load_existing_solution_artifact(path)
    payload["issue_key"] = issue_key
    if analysis is not None:
        payload["analysis"] = analysis.model_dump(mode="json")
    if structured_edit is not None:
        payload["structured_edit"] = structured_edit.model_dump(mode="json")
    if clear_patch:
        payload.pop("patch", None)
    if patch is not None:
        payload["patch"] = patch.model_dump(mode="json")
    if decision is not None:
        payload["decision"] = decision
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    elif decision != "rejected":
        payload.pop("rejection_reason", None)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _load_existing_solution_artifact(path: Path) -> dict[str, Any]:
    """Load an existing solution artifact file if present."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
