"""Plan future batch promotion without wiring it into live finding sync."""

from collections import defaultdict
from collections.abc import Mapping, Sequence

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.finding_batch import FindingBatchGroup
from zeroone_ops.models.finding_batch_promotion import (
    FindingBatchDecisionReason,
    FindingBatchFindingDecision,
    FindingBatchMemberIdentity,
    FindingBatchOwnershipConflict,
    FindingBatchPromotionPlan,
    FindingBatchPromotionUnit,
)
from zeroone_ops.models.finding_sync import FindingSyncRecord
from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.remediation import (
    is_remediation_eligible_category,
    normalize_remediation_category,
)
from zeroone_ops.services.intake.finding_batch_ownership import (
    FindingBatchOwnershipIndex,
    build_finding_batch_ownership,
    finding_batch_group,
    retains_finding_batch_ownership,
    work_item_batch_group,
)
from zeroone_ops.services.intake.finding_promotion_capacity_service import DEFAULT_SOURCE_PRIORITY
from zeroone_ops.services.intake.finding_workflow_policy_service import FindingWorkflowPolicyService

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class FindingBatchPromotionService:
    """Select provider-neutral promotion units without IDs, clocks, or writes."""

    def __init__(self, policy_service: FindingWorkflowPolicyService | None = None) -> None:
        """Retain the existing pure per-finding policy evaluator."""
        self.policy_service = policy_service or FindingWorkflowPolicyService()

    def plan(
        self,
        *,
        findings: Sequence[NormalizedFinding],
        records: Sequence[FindingSyncRecord],
        policy_state: PolicyState,
        repository_scope: str,
        max_active_work_items: int,
        max_findings_per_work_item: int = 10,
        source_priorities: Mapping[str, int] | None = None,
    ) -> FindingBatchPromotionPlan:
        """Return a dormant plan from supplied authority, never inferring absence."""
        if max_active_work_items < 1 or max_findings_per_work_item < 1:
            raise ValueError("Promotion capacity and batch size must be positive.")
        inventory: dict[tuple[str, str], NormalizedFinding] = {}
        for finding in findings:
            key = finding.source_id, finding.finding_id
            previous = inventory.setdefault(key, finding)
            if previous != finding:
                raise ValueError("Conflicting normalized findings share an identity.")
        ownership = build_finding_batch_ownership(
            records=records, repository_scope=repository_scope
        )
        reasons: dict[FindingBatchMemberIdentity, FindingBatchDecisionReason] = {}
        eligible_new: list[NormalizedFinding] = []
        for finding in inventory.values():
            identity = _identity(repository_scope, finding)
            reason = self._initial_reason(finding, policy_state, ownership, repository_scope)
            if reason is None:
                eligible_new.append(finding)
            else:
                reasons[identity] = reason
        proposals = self._new_proposals(eligible_new, repository_scope, max_findings_per_work_item)
        candidates = [*proposals, *self._existing_candidates(ownership, inventory, policy_state)]
        priorities = source_priorities or {}
        candidates.sort(key=lambda unit: _unit_order(unit, priorities))
        available = max(max_active_work_items - ownership.active_work_item_count, 0)
        selected_new: list[FindingBatchPromotionUnit] = []
        selected_existing: list[FindingBatchPromotionUnit] = []
        selected_groups: set[FindingBatchGroup] = set()
        for unit in candidates:
            selected = available > 0 and (
                unit.existing_record is not None
                or unit.group is None
                or unit.group not in selected_groups
            )
            if selected:
                available -= 1
                if unit.group is not None:
                    selected_groups.add(unit.group)
                if unit.existing_record is None:
                    selected_new.append(unit)
                else:
                    selected_existing.append(unit)
            for member in unit.members:
                identity = _identity(repository_scope, member)
                if (member.source_id, member.finding_id) in inventory:
                    if selected:
                        reasons[identity] = "selected"
                    elif unit.existing_record is None and unit.group in selected_groups:
                        reasons[identity] = "group_reserved"
                    else:
                        reasons[identity] = "promotion_capacity_exhausted"
        for finding in eligible_new:
            reasons.setdefault(_identity(repository_scope, finding), "batch_overflow")
        return FindingBatchPromotionPlan(
            selected_new=tuple(_copy_unit(unit) for unit in selected_new),
            selected_existing=tuple(_copy_unit(unit) for unit in selected_existing),
            decisions=tuple(
                FindingBatchFindingDecision(identity=identity, reason=reason)
                for identity, reason in sorted(reasons.items())
            ),
            conflicts=tuple(
                FindingBatchOwnershipConflict(
                    issue_numbers=numbers[:10], omitted_issue_count=max(len(numbers) - 10, 0)
                )
                for numbers in ownership.conflicts[:10]
            ),
            active_work_item_count=ownership.active_work_item_count,
            omitted_conflict_count=max(len(ownership.conflicts) - 10, 0),
        )

    def _initial_reason(
        self,
        finding: NormalizedFinding,
        policy: PolicyState,
        ownership: FindingBatchOwnershipIndex,
        scope: str,
    ) -> FindingBatchDecisionReason | None:
        identity = _identity(scope, finding)
        group = finding_batch_group(repository_scope=scope, finding=finding)
        if identity in ownership.suppressed:
            return "dismissed"
        decision = self.policy_service.decide_promotion(finding=finding, policy_state=policy)
        if decision.disposition != "promote":
            return (
                "severity_disabled"
                if decision.reason == "severity_disabled"
                else "issue_class_excluded"
            )
        if identity in ownership.conflict_members or (
            group is not None and group in ownership.conflict_groups
        ):
            return "ownership_conflict"
        if identity in ownership.owned:
            return "owned"
        if group is not None and group in ownership.reserved_groups:
            return "group_reserved"
        return None

    def _existing_candidates(
        self,
        ownership: FindingBatchOwnershipIndex,
        findings: Mapping[tuple[str, str], NormalizedFinding],
        policy: PolicyState,
    ) -> list[FindingBatchPromotionUnit]:
        candidates: list[FindingBatchPromotionUnit] = []
        for record in ownership.records:
            work_item = record.work_item
            if (
                record.issue_number in ownership.conflict_issues
                or not retains_finding_batch_ownership(record)
                or work_item.status not in {"candidate", "policy_deferred", "capacity_deferred"}
                or work_item.claim is not None
                or work_item.linked_change_request is not None
            ):
                continue
            if work_item.batch is None:
                current = findings.get((work_item.source.source, work_item.source.source_item_key))
                members = [current] if current is not None else []
            else:
                originals = {member.finding_id: member for member in work_item.batch.members}
                members = [
                    findings.get((work_item.batch.group.source_id, observation.finding_id))
                    or (
                        observation.last_confirmed_finding or originals[observation.finding_id]
                    ).to_finding()
                    for observation in work_item.batch.observations
                    if observation.last_confirmed_presence == "detected"
                ]
            members = [
                member
                for member in members
                if _identity(work_item.source.repository_scope or "", member)
                not in ownership.suppressed
                and self.policy_service.decide_promotion(
                    finding=member, policy_state=policy
                ).disposition
                == "promote"
            ]
            if members:
                candidates.append(
                    FindingBatchPromotionUnit(
                        group=work_item_batch_group(work_item),
                        members=tuple(sorted(members, key=_member_order)),
                        existing_record=record,
                    )
                )
        return candidates

    @staticmethod
    def _new_proposals(
        findings: Sequence[NormalizedFinding], scope: str, limit: int
    ) -> list[FindingBatchPromotionUnit]:
        groups: dict[FindingBatchGroup, list[NormalizedFinding]] = defaultdict(list)
        proposals: list[FindingBatchPromotionUnit] = []
        for finding in findings:
            group = finding_batch_group(repository_scope=scope, finding=finding)
            if group is None:
                proposals.append(FindingBatchPromotionUnit(group=None, members=(finding,)))
            else:
                groups[group].append(finding)
        for group, members in groups.items():
            ordered = sorted(members, key=_member_order)
            signatures = {_requirements(member) for member in ordered}
            if (
                limit == 1
                or len(signatures) > 1
                or any(
                    not is_remediation_eligible_category(member.remediation_context.category)
                    for member in ordered
                )
            ):
                proposals.extend(
                    FindingBatchPromotionUnit(group=group, members=(member,)) for member in ordered
                )
            else:
                proposals.append(
                    FindingBatchPromotionUnit(group=group, members=tuple(ordered[:limit]))
                )
        return proposals


def _identity(scope: str, finding: NormalizedFinding) -> FindingBatchMemberIdentity:
    return scope, finding.source_id, finding.finding_id, "remediation"


def _member_order(finding: NormalizedFinding) -> tuple[int, str, str]:
    return _SEVERITY_ORDER[finding.severity], finding.source_id, finding.finding_id


def _requirements(finding: NormalizedFinding) -> tuple[object, ...]:
    context = finding.remediation_context
    return (
        normalize_remediation_category(context.category),
        context.expected_change,
        context.constraints,
        tuple(context.validation_commands),
        tuple(sorted(set(context.acceptance_criteria))),
    )


def _unit_order(
    unit: FindingBatchPromotionUnit, priorities: Mapping[str, int]
) -> tuple[int, int, tuple[str, str, str, str], tuple[tuple[str, str], ...], int]:
    member = min(unit.members, key=_member_order)
    group_key = (
        unit.group.key
        if unit.group is not None
        else (
            "",
            member.repository_path,
            member.source_id,
            member.remediation_context.diagnostic_code or "",
        )
    )
    return (
        priorities.get(member.source_id, DEFAULT_SOURCE_PRIORITY),
        _SEVERITY_ORDER[member.severity],
        group_key,
        tuple(sorted((finding.source_id, finding.finding_id) for finding in unit.members)),
        unit.existing_record.issue_number if unit.existing_record is not None else 0,
    )


def _copy_unit(unit: FindingBatchPromotionUnit) -> FindingBatchPromotionUnit:
    record = unit.existing_record
    return FindingBatchPromotionUnit(
        group=unit.group,
        members=tuple(member.model_copy(deep=True) for member in unit.members),
        existing_record=(
            FindingSyncRecord(
                work_item=record.work_item.model_copy(deep=True),
                issue_number=record.issue_number,
                issue_url=record.issue_url,
                is_open=record.is_open,
            )
            if record is not None
            else None
        ),
    )
