# ZeroOne Ops Roadmap

## Purpose

This roadmap is the short execution view for ZeroOne Ops. It answers three
questions:

- what is already shipped
- what the team is focused on now
- what is intentionally parked for later

Detailed implementation history belongs in the design documents and Git
history, not here.

## Implemented

- staged GitHub/GitLab change-request review with durable continuity, bounded
  comments, defect-grounding guidance, verified remediation context, and
  recoverable review-projection repair
- normalized SonarQube and SARIF ingestion with complete pagination, canonical
  configured source IDs, per-artifact severity mappings, and unavailable-source
  isolation; incomplete inventories never establish absence
- provider-native policy and work-item issues, shared promotion/intake/recovery
  coordination, lifecycle reconciliation, and derived operational summaries
- source-priority and severity ranking, dismissal suppression, protected active
  capacity, reversible deferral, and complete-inventory `no_longer_detected`
  reconciliation
- promotion-time file/rule batching for new work, defaulting to five findings
  per work item; existing singles remain independent and publication remains
  one-file and all-or-nothing; see [Remediation Batching](#remediation-batching)
- shared remediation execution with one-file patch enforcement, untrusted prompt
  evidence, validation commands, rollback, and bounded publication retries
- opt-in baseline-aware validation separating execution health, bounded
  correction, and publication eligibility, with supported MyPy/Ruff diagnostic
  comparison and sanitized operator failure evidence
- operator-controlled same-request review revisions and explicit recovery from
  blocked or closed-unmerged work, preserving linkage and execution evidence
- operator-facing validation evidence and **Change Rationale** in work items and
  PR/MRs; mandatory structural claim validation is not semantic verification
- safe dirty-workspace diagnostics and exact configured untracked runtime-output
  exemptions, without weakening protection of operator changes
- optional MLflow workflow tracing, configurable bounded repository guidance,
  source-focused dogfood, and release-pinned GitHub/GitLab installation templates
- v1 retirement of dashboard runtime, commands, and configuration aliases, with
  strict replacement guidance and explicit local-state safeguards; see the
  [migration guide](migration-v1.md)
- shared provider-neutral orchestration with provider-local transport and
  authorization, automated architecture checks, and seven-day dependency cooldowns

### Remediation Batching

Implemented and accepted on both providers: default-five new file/rule batches,
frozen membership, complete execution coverage, and one-file publication without
consolidating existing issues. The [functional contract](design/functional/functional-design-remediation-batching.md)
and [technical contract](design/technical/technical-design-remediation-batching.md)
own implementation detail; completed slice checklists remain in Git history.

### Accepted RC Validation

The operator confirmed latest-RC validation on GitHub and GitLab on 2026-10-29,
including batching, review/requeue, same-request revisions, failure recovery,
manual merge-conflict recovery, merge reconciliation, and batch evidence handoff.
This is operator-reported acceptance, separate from automated checks; the exact
RC tag was not recorded here. No additional remote validation was run for this
documentation update.

The [review-precision investigation](../tests/zeroone_ops/services/review/pipeline/fixtures/precision_v1/README.md),
[Luna evaluation](../tests/zeroone_ops/services/review/pipeline/fixtures/precision_v1/live-evaluation-2026-10-28.md),
and [production-model Terra evaluation](../tests/zeroone_ops/services/review/pipeline/fixtures/precision_v1/live-evaluation-terra-2026-10-28.md)
retain provenance and limitations. The bounded results do not establish general
accuracy; both 18-call evaluation budgets are exhausted.

## Current Focus

### V1 Release Readiness

- [ ] confirm remaining GitLab installations have completed issue-mode cutover
  and local-state cleanup before tagging v1
- [ ] confirm final release-PR checks and migration/template changes are merged
- [ ] publish v1 through Release Please, verify the versioned image, and
  smoke-test the published image before enabling installation schedules

## Parked For Later (Post-v1)

- broader end-to-end scenario fixtures across intake, policy, remediation,
  provider-native change requests, lifecycle, and summaries on both providers
- stable machine-readable run summaries alongside human CLI output, including
  finding, policy decision, validation, request, lifecycle, and bounded errors
- automatic merge-conflict detection and operator guidance with preserved
  linkage; no automatic rebases or force-pushes
- safe retry in reused workspaces after a failed revision push without
  discarding unpublished operator commits
- bounded self-contained review findings as an ongoing quality refinement:
  behavior, causal impact, scoped fix, and locations, with expanded explanation
  only where needed
- mutable GitHub/GitLab review summaries guarded by reviewed revision, keeping
  line-level comments and durable continuity evidence separate
- shared glob semantics for review include/exclude paths and helper context,
  preserving repository-relative path safety
- optional provider-native remediation reviewer assignment, with explicit
  GitHub user/team and GitLab user-ID handling, separate from assignees
- external API/database-backed control plane
- additional structured finding adapters and a later shared cross-source
  reconciliation/deduplication stage
- richer developer feedback consumption for review notes and broader review
  evaluator growth
- multi-file remediation and automated test-repair workflows
- add read-only `config validate` and advisory `config migrate`
  tooling for deprecated aliases, missing provider selection, and unavailable
  configured fixture or SARIF paths; v1 continues to use load-time errors,
  deprecation warnings, and configuration documentation without file rewrites
- consider optional workflow-scoped preflight commands only after workflow-local
  diagnostics prove insufficient; keep any future readiness checks read-only
  and free of remediation, lifecycle, or provider-state writes
- consider an argv-style alternative to shell-based validation commands after
  the executable-CI-policy trust model has been live-reviewed
- make MLflow tracing an optional package extra after tracing rollout feedback
  confirms the supported installation profile
- optional derived file-level finding inventories and later goal-based work;
  preserve individual findings and provenance. The parked file-grouping designs
  are background, not prerequisites for implemented promotion-time batching
- provider-bound conditional work-item transitions and atomic claims, so
  concurrent finding sync, remediation, recovery, and lifecycle jobs do not
  rely on CI scheduling or resource groups for correctness

## Reference Docs

- [README.md](README.md)
- [runbook.md](runbook.md)
- [design/README.md](design/README.md)
- [design/functional/functional-design-finding-ingestion.md](design/functional/functional-design-finding-ingestion.md)
- [design/technical/technical-design-finding-ingestion.md](design/technical/technical-design-finding-ingestion.md)
- [design/functional/functional-design-finding-file-grouping.md](design/functional/functional-design-finding-file-grouping.md)
- [design/technical/technical-design-finding-file-grouping.md](design/technical/technical-design-finding-file-grouping.md)
- [design/functional/functional-design-remediation-batching.md](design/functional/functional-design-remediation-batching.md)
- [design/technical/technical-design-remediation-batching.md](design/technical/technical-design-remediation-batching.md)
- [design/functional/functional-design-work-item-state-projection.md](design/functional/functional-design-work-item-state-projection.md)
- [design/technical/technical-design-work-item-state-projection.md](design/technical/technical-design-work-item-state-projection.md)
- [design/functional/functional-design-remediation-recovery.md](design/functional/functional-design-remediation-recovery.md)
- [design/technical/technical-design-remediation-recovery.md](design/technical/technical-design-remediation-recovery.md)
- [design/functional/functional-design-remediation-review-feedback.md](design/functional/functional-design-remediation-review-feedback.md)
- [design/technical/technical-design-remediation-review-feedback.md](design/technical/technical-design-remediation-review-feedback.md)
- [design/functional/functional-design-remediation-semantic-safety.md](design/functional/functional-design-remediation-semantic-safety.md)
- [design/technical/technical-design-remediation-semantic-safety.md](design/technical/technical-design-remediation-semantic-safety.md)
- [design/functional/functional-design-pr-review-staged-pipeline.md](design/functional/functional-design-pr-review-staged-pipeline.md)
