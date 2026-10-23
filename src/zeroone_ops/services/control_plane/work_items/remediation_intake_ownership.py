"""Check batch ownership against the complete supplied open intake inventory."""

import logging
from collections.abc import Sequence

from zeroone_ops.models.finding_sync import FindingSyncRecord
from zeroone_ops.models.remediation_intake import RemediationIntakeRecord
from zeroone_ops.services.intake.finding_batch_ownership import build_finding_batch_ownership

LOGGER = logging.getLogger(__name__)


def conflicting_intake_batches(
    records: Sequence[RemediationIntakeRecord],
) -> frozenset[tuple[str, int]]:
    """Withhold ambiguous batches without changing historical single selection.

    Each repository is indexed independently. No provider discovery is added;
    the existing read-before-write concurrency limitation still applies.
    """
    scopes = {
        record.work_item.source.repository_scope
        for record in records
        if record.work_item.batch is not None
    }
    conflicts: set[tuple[str, int]] = set()
    for scope in sorted(scope for scope in scopes if scope is not None):
        inventory = tuple(
            FindingSyncRecord(record.work_item, record.issue_number, record.issue_url, True)
            for record in records
            if record.work_item.source.repository_scope == scope
        )
        ownership = build_finding_batch_ownership(records=inventory, repository_scope=scope)
        conflicts.update(
            (scope, record.issue_number)
            for record in inventory
            if record.work_item.batch is not None
            and record.issue_number in ownership.conflict_issues
        )

    if conflicts:
        LOGGER.warning(
            "Withheld ambiguous batch intake: count=%s issues=%s omitted=%s",
            len(conflicts),
            sorted(conflicts)[:10],
            max(0, len(conflicts) - 10),
        )
    return frozenset(conflicts)
