# Design Index

## Purpose

This index distinguishes the current design contracts that guide new work from
historical records that explain how ZeroOne Ops reached its present architecture.

## Current Contracts

- [Finding ingestion functional design](functional/functional-design-finding-ingestion.md)
  and [technical design](technical/technical-design-finding-ingestion.md)
- [Work-item state projection functional design](functional/functional-design-work-item-state-projection.md)
  and [technical design](technical/technical-design-work-item-state-projection.md)
- [GitLab issue control-plane functional design](functional/functional-design-gitlab-issue-control-plane.md)
  and [technical design](technical/technical-design-gitlab-issue-control-plane.md)
- [Remediation recovery functional design](functional/functional-design-remediation-recovery.md)
  and [technical design](technical/technical-design-remediation-recovery.md)
- [Remediation validation-feedback functional design](functional/functional-design-remediation-validation-feedback.md)
  and [technical design](technical/technical-design-remediation-validation-feedback.md)
- [Remediation semantic-safety functional design](functional/functional-design-remediation-semantic-safety.md)
  and [technical design](technical/technical-design-remediation-semantic-safety.md)
- [Runtime workspace ownership technical design](technical/technical-design-runtime-workspace-ownership.md)
- [Staged review-pipeline functional design](functional/functional-design-pr-review-staged-pipeline.md)
  and [technical design](technical/technical-design-pr-review-staged-pipeline.md)

Use the [roadmap](../roadmap.md) to identify the active implementation topic,
then follow the relevant current contract.

- [Promotion-time file/rule batching functional design](functional/functional-design-remediation-batching.md)
  and [technical design](technical/technical-design-remediation-batching.md)
  describe activated default-five batches,
  new work items only, and one-file execution on both providers. Existing
  single-finding issues are not migrated or consolidated.
  Shared sync, intake and complete execution/recovery use provider-parity tests;
  operator UX and payload guards are activated. Live provider validation and
  release-candidate acceptance remain separate, unchecked roadmap gates.

## Proposed And Parked Designs

- [Finding file grouping functional design](functional/functional-design-finding-file-grouping.md)
  and [technical design](technical/technical-design-finding-file-grouping.md)
  remain parked background for derived inventories. They are not prerequisites
  for promotion-time batching.

## Retirement Audits

- [Post-v1 code cleanup audit](technical/technical-audit-post-v1-cleanup.md)
  records unused paths, replacement coverage, retained compatibility, and ordered
  behavior-preserving follow-ups. Implementation status lives in the roadmap.
- [Legacy dashboard dependency and retirement audit](technical/technical-audit-legacy-dashboard-retirement.md)
  records shared dependencies, release-window evidence, and removal prerequisites.
  Runtime retirement is implemented for v1; see the [migration guide](../migration-v1.md).
  Operator cutover confirmation remains required before tagging the release.

## Historical Records

Historical designs preserve rationale, rollout decisions, and compatibility
context. They do not define new product behavior unless a change explicitly
changes an explicitly retained compatibility decoder. Dashboard runtime is
retired; these records must not be used as active installation instructions.

- foundational SonarQube and GitLab-first designs
- GitLab dashboard storage, remediation, policy, and feedback designs
- initial GitLab-first pull-request review designs
- completed GitHub platform rollout, configuration migration, and review-package
  layout plans

Each historical record carries a status banner that points readers back to this
index and the current contracts.
