"""Derive read-only batch counts and bounded operator presentation."""

import html
from dataclasses import dataclass

from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.remediation import remediation_source_display_name
from zeroone_ops.models.work_item import WorkItemState, work_item_resolution_display_name
from zeroone_ops.services.control_plane.work_items.work_item_execution_view import (
    current_batch_rejection_view,
)
from zeroone_ops.services.intake.finding_batch_ownership import is_safe_unstarted_batch
from zeroone_ops.services.intake.finding_workflow_policy_service import FindingWorkflowPolicyService
from zeroone_ops.services.remediation.batch_analysis_rejection_presentation import (
    render_batch_analysis_stop_lines,
)


@dataclass(frozen=True)
class BatchWorkItemView:
    """Keep observations, policy evaluation, and recorded attempt counts distinct."""

    original: int
    detected: int
    absent: int
    unknown_freshness: int
    policy_excluded: int | None
    planned_targeted: int | None
    recorded_attempt: int


def build_batch_work_item_view(
    work_item: WorkItemState, policy: PolicyState | None = None
) -> BatchWorkItemView:
    """Derive counts without loading policy or changing work-item authority."""
    batch = work_item.batch
    if batch is None:
        raise ValueError("A batch view requires batch state.")
    detected = sum(o.last_confirmed_presence == "detected" for o in batch.observations)
    eligible = (
        len(FindingWorkflowPolicyService().eligible_batch_members(work_item, policy))
        if policy is not None
        else None
    )
    return BatchWorkItemView(
        original=len(batch.members),
        detected=detected,
        absent=len(batch.members) - detected,
        unknown_freshness=sum(o.freshness == "unknown" for o in batch.observations),
        policy_excluded=detected - eligible if eligible is not None else None,
        planned_targeted=eligible,
        recorded_attempt=len(work_item.batch_attempt.members) if work_item.batch_attempt else 0,
    )


def render_batch_task_lines(
    work_item: WorkItemState, policy: PolicyState | None = None
) -> list[str]:
    """Render bounded display evidence, never a substitute for complete machine state."""
    batch = work_item.batch
    if batch is None:
        raise ValueError("A batch task requires batch state.")
    view = build_batch_work_item_view(work_item, policy)
    lines = [
        "This issue tracks one file/rule remediation batch managed by ZeroOne Ops.",
        "Membership is frozen; observation changes do not resize this batch.",
        "",
        "## Task",
        "",
        f"- File: {literal(batch.group.file_path)}",
        f"- Source: {literal(remediation_source_display_name(batch.group.source_id))} "
        f"({literal(batch.group.source_id)})",
        f"- Rule: {literal(batch.group.rule_id)}",
        "",
        "## Status",
        "",
        f"- Status: `{work_item.status}`",
        f"- Priority: `{work_item.severity or 'unknown'}`",
        *(
            [f"- Resolution: {work_item_resolution_display_name(work_item.resolution)}"]
            if work_item.resolution is not None
            else []
        ),
        f"- Original findings: {view.original}",
        f"- Last-confirmed detected: {view.detected}; absent: {view.absent}",
        f"- Unknown freshness: {view.unknown_freshness}",
        f"- Policy-excluded: {_count(view.policy_excluded)}",
        f"- Planned targets: {_count(view.planned_targeted)}",
        f"- Recorded attempt targets: {view.recorded_attempt}",
        "- Attempted means targeted by a change, not scanner-verified as resolved.",
        "- Merge completion does not establish scanner absence.",
        "",
        "## Next Action",
        "",
        _next_action(work_item),
    ]
    rejection = current_batch_rejection_view(work_item)
    if rejection is not None:
        lines.extend(render_batch_analysis_stop_lines(rejection))
        if work_item.linked_change_request is not None:
            lines.append(f"- Existing change request: {work_item.linked_change_request.web_url}")
        failure = work_item.execution_failure
        if failure is not None and failure.execution_url is not None:
            lines.append(f"- Workflow logs: {failure.execution_url}")
    lines.extend(
        [
            "",
            "## Members",
            "",
            "| Line | Last confirmed | Freshness | Message |",
            "| --- | --- | --- | --- |",
        ]
    )
    observations = {o.finding_id: o for o in batch.observations}
    for member in batch.members[:10]:
        observation = observations[member.finding_id]
        evidence = observation.last_confirmed_finding or member
        lines.append(
            f"| {evidence.line_start or 'unknown'} | {observation.last_confirmed_presence} "
            f"| {observation.freshness} | {literal(evidence.summary[:300])} |"
        )
    if len(batch.members) > 10:
        lines.append(
            f"\n{len(batch.members) - 10} display rows omitted; machine state retains all members."
        )
    lines.extend(
        ["", "<details>", "<summary>Diagnostic details and observation references</summary>", ""]
    )
    for member in batch.members[:10]:
        observation = observations[member.finding_id]
        confirmed_run = literal((observation.last_confirmed_sync_run_id or "unknown")[:300])
        lines.append(
            f"- {literal(member.finding_id[:300])}: {literal(member.summary[:300])}; "
            f"sync {literal(observation.sync_run_id[:300])}; "
            f"last confirmed sync {confirmed_run}; "
            f"observed {observation.observed_at.isoformat()}"
        )
    lines.extend(["", "</details>", "", "## Closure", ""])
    if is_safe_unstarted_batch(work_item):
        lines.append(
            "Manual closure releases this unstarted batch; still-reported findings may reappear. "
            "Dismiss instead to suppress its exact members."
        )
    else:
        lines.append(
            "Manual closure does not release protected batch ownership. "
            "Use supported recovery actions or reconcile the linked request."
        )
    return lines


def _count(value: int | None) -> str:
    return str(value) if value is not None else "not evaluated"


def _next_action(work_item: WorkItemState) -> str:
    if current_batch_rejection_view(work_item) is not None:
        return (
            "Inspect the latest attempt explanation and any linked request before deciding on "
            "manual correction or a new `/zeroone remediation requeue` command on this issue."
        )
    if work_item.status == "blocked":
        return (
            "Address the blocker, then post `/zeroone remediation requeue` here; "
            "use `/zeroone remediation dismiss` to stop automation."
        )
    if work_item.status == "review_feedback_required":
        return "Address review feedback, then post `/zeroone remediation requeue` on this issue."
    return {
        "approved": (
            "Await remediation; executable scope is selected against current policy at intake."
        ),
        "candidate": "Await policy and available capacity.",
        "in_progress": "Inspect the linked request and recorded execution evidence.",
        "review_revision_queued": "Await the authorized revision of the linked request.",
        "policy_deferred": "Await policy eligibility; this is not remediation completion.",
        "capacity_deferred": "Await available remediation capacity.",
        "completed": "No action required; inspect the terminal resolution below.",
        "dismissed": "Automation is suppressed for these exact members.",
    }.get(work_item.status, "Inspect the authoritative status and execution evidence.")


def literal(value: str) -> str:
    """Keep scanner-controlled text literal within Markdown tables and prose."""
    escaped = html.escape(" ".join(value.splitlines()))
    for character in "\\`*_[]|":
        escaped = escaped.replace(character, f"&#{ord(character)};")
    return escaped
