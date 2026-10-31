# Workflows

GitHub and GitLab issue mode share the same workflow boundaries. Provider labels
help discover records; persisted machine state on the issue is authoritative.

## Findings, Policy, And Remediation

Scanners produce findings before sync evaluates policy and available capacity.
Compatible new findings can form one file/rule batch; existing single-finding
issues are not consolidated. Remediation claims approved work and prepares one
one-file PR/MR, subject to analysis, validation, and publication safeguards.

Use [Operating The Control Plane](runbook.md#operating-the-control-plane) for the
workflow and command reference, and [Normal Operations](runbook.md#normal-operations)
for CI ordering. The [supported v1 scope](runbook.md#supported-v1-scope) explains
batch ownership and execution limits.

## Review And Operator Requeue

Review proposes candidates, reconciles their meaning, validates the artifact,
and publishes the same finalized result to the request and linked work item.
Repeated reviews track earlier concerns separately from new findings.

See the [review flow diagram](review-flow-mermaid.md),
[expected review behavior](runbook.md#expected-review-workflow-behavior), and
[review judgment strategy](review-bot-judgment-strategy.md).
Where supported, `/zeroone remediation requeue` belongs on the authoritative
work-item issue, not the PR/MR. Follow the issue's next-action guidance and the
[recovery steps](runbook.md#recovery-steps).

## Completion And Evidence

Lifecycle reconciliation owns merged and closed-unmerged request outcomes.
Scanner disappearance, merge completion, and model-provided Change Rationale
are different kinds of evidence; none substitutes for validation or review.
See [reconciliation behavior](runbook.md#expected-reconciliation-workflow-behavior)
and the [expected request shape](runbook.md#expected-merge-request-shape).
