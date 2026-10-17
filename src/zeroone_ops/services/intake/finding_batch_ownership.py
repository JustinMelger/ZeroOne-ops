"""Pure ownership checks for dormant batch promotion planning."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.finding_batch import FindingBatchGroup
from zeroone_ops.models.finding_batch_promotion import FindingBatchMemberIdentity
from zeroone_ops.models.finding_sync import FindingSyncRecord
from zeroone_ops.models.work_item import WorkItemState, is_active_remediation_status


def is_safe_unstarted_batch(work_item: WorkItemState) -> bool:
    """Recognize batch work whose native closure may release ownership."""
    return (
        work_item.batch is not None
        and work_item.status in {"candidate", "approved"}
        and work_item.attempt_number == 1
        and not work_item.recovery_events
        and all(
            evidence is None
            for evidence in (
                work_item.claim,
                work_item.linked_change_request,
                work_item.publication_retry,
                work_item.execution_failure,
                work_item.semantic_safety,
                work_item.projected_review,
                work_item.review_revision_request,
                work_item.last_revision_command,
                work_item.review_action_required_at,
            )
        )
    )


def retains_finding_batch_ownership(record: FindingSyncRecord) -> bool:
    """Separate terminal and safely closed batch work from protected authority."""
    return record.work_item.status not in {"completed", "dismissed"} and not (
        not record.is_open and is_safe_unstarted_batch(record.work_item)
    )


def finding_batch_group(
    *, repository_scope: str, finding: NormalizedFinding
) -> FindingBatchGroup | None:
    """Resolve complete scope independently of batching category compatibility."""
    return _scope_group(
        repository_scope,
        finding.repository_path,
        finding.source_id,
        finding.remediation_context.diagnostic_code,
    )


def _scope_group(
    repository_scope: str, path: str | None, source: str, rule: str | None
) -> FindingBatchGroup | None:
    if not path or not rule:
        return None
    try:
        return FindingBatchGroup(
            repository_scope=repository_scope, file_path=path, source_id=source, rule_id=rule
        )
    except ValidationError:
        return None


def work_item_batch_group(work_item: WorkItemState) -> FindingBatchGroup | None:
    """Resolve reservations for historical singles as well as explicit batches."""
    if work_item.batch is not None:
        return work_item.batch.group
    return _scope_group(
        work_item.source.repository_scope or "",
        work_item.file_path,
        work_item.source.source,
        work_item.remediation_context.diagnostic_code,
    )


def work_item_member_identities(work_item: WorkItemState) -> tuple[FindingBatchMemberIdentity, ...]:
    """Expand frozen members without mistaking a synthetic key for a finding."""
    scope = work_item.source.repository_scope or ""
    if work_item.batch is None:
        return ((scope, work_item.source.source, work_item.source.source_item_key, work_item.kind),)
    return tuple(
        (scope, member.source_id, member.finding_id, work_item.kind)
        for member in work_item.batch.members
    )


@dataclass(frozen=True)
class FindingBatchOwnershipIndex:
    """Retain normalized discovery decisions, without accessing provider transport."""

    records: tuple[FindingSyncRecord, ...]
    owned: frozenset[FindingBatchMemberIdentity]
    suppressed: frozenset[FindingBatchMemberIdentity]
    reserved_groups: frozenset[FindingBatchGroup]
    conflict_issues: frozenset[int]
    conflict_members: frozenset[FindingBatchMemberIdentity]
    conflict_groups: frozenset[FindingBatchGroup]
    conflicts: tuple[tuple[int, ...], ...]
    active_work_item_count: int


def build_finding_batch_ownership(
    *, records: Sequence[FindingSyncRecord], repository_scope: str
) -> FindingBatchOwnershipIndex:
    """Index exact authority and conservatively retain conflicting records."""
    unique: dict[int, FindingSyncRecord] = {}
    suppressed: set[FindingBatchMemberIdentity] = set()
    owners: dict[FindingBatchMemberIdentity, set[int]] = defaultdict(set)
    work_item_ids: dict[str, set[int]] = defaultdict(set)
    source_identities: dict[tuple[str, str, str | None, str], set[int]] = defaultdict(set)
    groups: dict[FindingBatchGroup, set[int]] = defaultdict(set)
    batch_issues: set[int] = set()
    active: set[int] = set()
    conflicts: set[tuple[int, ...]] = set()
    for record in records:
        work_item = record.work_item
        if work_item.source.repository_scope != repository_scope:
            continue
        number = record.issue_number
        previous = unique.setdefault(number, record)
        if previous != record:
            conflicts.add((number,))
        identities = work_item_member_identities(work_item)
        if work_item.status == "dismissed":
            suppressed.update(identities)
        if not retains_finding_batch_ownership(record):
            continue
        work_item_ids[work_item.work_item_id].add(number)
        source_identities[work_item.identity_key].add(number)
        if is_active_remediation_status(work_item.status):
            active.add(number)
        if work_item.batch is not None:
            batch_issues.add(number)
        for identity in identities:
            owners[identity].add(number)
        group = work_item_batch_group(work_item)
        if group is not None:
            groups[group].add(number)
    conflicts.update(tuple(sorted(numbers)) for numbers in owners.values() if len(numbers) > 1)
    conflicts.update(
        tuple(sorted(numbers)) for numbers in work_item_ids.values() if len(numbers) > 1
    )
    conflicts.update(
        tuple(sorted(numbers)) for numbers in source_identities.values() if len(numbers) > 1
    )
    conflicts.update(
        tuple(sorted(numbers))
        for numbers in groups.values()
        if len(numbers) > 1 and numbers & batch_issues
    )
    conflict_issues = frozenset(number for numbers in conflicts for number in numbers)
    return FindingBatchOwnershipIndex(
        records=tuple(unique[number] for number in sorted(unique)),
        owned=frozenset(owners),
        suppressed=frozenset(suppressed),
        reserved_groups=frozenset(groups),
        conflict_issues=conflict_issues,
        conflict_members=frozenset(
            identity for identity, numbers in owners.items() if numbers & conflict_issues
        ),
        conflict_groups=frozenset(
            group for group, numbers in groups.items() if numbers & conflict_issues
        ),
        conflicts=tuple(sorted(conflicts)),
        active_work_item_count=len(active),
    )
