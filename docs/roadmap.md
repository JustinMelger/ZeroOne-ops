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

What we have built so far. These points describe implemented capabilities,
not a dated release sequence; active work and future ideas remain separate below.

<div class="zeroone-milestones" markdown="1">

- **Governed Code Review**

    Staged GitHub/GitLab change-request review with durable continuity, bounded
    comments, defect-grounding guidance, verified remediation context, and
    recoverable review-projection repair

- **Scanner Finding Intake**

    Normalized SonarQube and SARIF ingestion with complete pagination, canonical
    configured source IDs, per-artifact severity mappings, and unavailable-source
    isolation; incomplete inventories never establish absence

- **Provider-Native Control Plane**

    Provider-native policy and work-item issues, shared promotion/intake/recovery
    coordination, lifecycle reconciliation, and derived operational summaries

- **Policy-Based Promotion**

    Source-priority and severity ranking, dismissal suppression, protected active
    capacity, reversible deferral, and complete-inventory `no_longer_detected`
    reconciliation

- **File/Rule Batching**

    Promotion-time file/rule batching for new work, defaulting to five findings
    per work item; existing singles remain independent and publication remains
    one-file and all-or-nothing; see [Remediation Batching](#remediation-batching)

- **Bounded Remediation**

    Shared remediation execution with one-file patch enforcement, untrusted prompt
    evidence, validation commands, rollback, and bounded publication retries

- **Baseline-Aware Validation**

    Opt-in baseline-aware validation separating execution health, bounded
    correction, and publication eligibility, with supported MyPy/Ruff diagnostic
    comparison and sanitized operator failure evidence

- **Review Revisions And Recovery**

    Operator-controlled same-request review revisions and explicit recovery from
    blocked or closed-unmerged work, preserving linkage and execution evidence

- **Operator Evidence**

    Operator-facing validation evidence and **Change Rationale** in work items and
    PR/MRs; mandatory structural claim validation is not semantic verification

- **Workspace Protection**

    Safe dirty-workspace diagnostics and exact configured untracked runtime-output
    exemptions, without weakening protection of operator changes

- **Tracing And Repository Guidance**

    Optional MLflow workflow tracing, configurable bounded repository guidance,
    source-focused dogfood, and release-pinned GitHub/GitLab installation templates

- **V1 Compatibility Cleanup**

    V1 retirement of dashboard runtime, commands, and configuration aliases, with
    strict replacement guidance and explicit local-state safeguards; see the
    [migration guide](migration-v1.md)

- **Shared Architecture**

    Shared provider-neutral orchestration with provider-local transport and
    authorization, automated architecture checks, and seven-day dependency cooldowns

- **Offline Remediation Scenarios**

    Offline GitHub/GitLab workflow scenarios from normalized findings through
    batch promotion, real intake, validation correction/rollback, local Git
    publication, recorded retry, and same-request revision success/failure;
    authorized requeue/replay, native permission-response handling, and
    merged/closed-unmerged lifecycle reconciliation;
    `just test-scenarios` and the normal Quality pytest job exercise
    deterministic external responses without model or provider credentials

- **Offline Review Scenarios**

    Offline GitHub/GitLab review scenarios covering real prompt/schema contracts,
    retained/dropped findings, verified batch projection, request isolation, and
    repeated-review overlap across successive commits, same-SHA reuse, and
    projection-only repair;
    scripted SDK responses test orchestration, not model precision

</div>

### Post-V1 Code Cleanup

All six behavior-preserving slices are implemented and verified: unused-code
removal, active continuity coverage, canonical sync storage, verified review
context, continuity/repair coordination, and remediation retry/revision routes.
The [cleanup audit](https://github.com/JustinMelger/ZeroOne-ops/blob/main/docs/design/technical/technical-audit-post-v1-cleanup.md)
retains coverage, verification, and ownership details. Completed slice
checklists remain in Git history.

### Remediation Batching

Implemented and accepted on both providers: default-five new file/rule batches,
frozen membership, complete execution coverage, and one-file publication without
consolidating existing issues. The [functional contract](https://github.com/JustinMelger/ZeroOne-ops/blob/main/docs/design/functional/functional-design-remediation-batching.md)
and [technical contract](https://github.com/JustinMelger/ZeroOne-ops/blob/main/docs/design/technical/technical-design-remediation-batching.md)
own implementation detail; completed slice checklists remain in Git history.

### Accepted RC Validation

The operator confirmed latest-RC validation on GitHub and GitLab on 2026-10-29,
including batching, review/requeue, same-request revisions, failure recovery,
manual merge-conflict recovery, merge reconciliation, and batch evidence handoff.
This is operator-reported acceptance, separate from automated checks; the exact
RC tag was not recorded here. No additional remote validation was run for this
documentation update.

The [review-precision investigation](https://github.com/JustinMelger/ZeroOne-ops/blob/main/tests/zeroone_ops/services/review/pipeline/fixtures/precision_v1/README.md),
[Luna evaluation](https://github.com/JustinMelger/ZeroOne-ops/blob/main/tests/zeroone_ops/services/review/pipeline/fixtures/precision_v1/live-evaluation-2026-10-28.md),
and [production-model Terra evaluation](https://github.com/JustinMelger/ZeroOne-ops/blob/main/tests/zeroone_ops/services/review/pipeline/fixtures/precision_v1/live-evaluation-terra-2026-10-28.md)
retain provenance and limitations. The bounded results do not establish general
accuracy; both 18-call evaluation budgets are exhausted.

### Operator Documentation Website

The operator-first Zensical site is published through main-only GitHub Pages
deployment, with strict builds and a read-only demo walkthrough. The original
site's navigation, search, and diagrams were verified live. The warm-neutral/teal
refresh, homepage cards, implemented milestones, documentation mark, and keyboard
states are implemented and locally verified; refreshed deployment acceptance
remains open below.

### V1 Release Readiness

V1 release readiness is complete: issue-mode cutover and local-state cleanup,
final release-PR checks and migration/template changes, and publication through
Release Please with versioned-image verification and a container smoke test.
This heading is retained for existing release-readiness links.

## Current Focus

- [ ] verify the refreshed styling and assets on the deployed Pages site after merge

## Parked For Later (Post-v1)

- broader end-to-end scenario fixtures across intake, policy, remediation,
  provider-native change requests, lifecycle, and summaries on both providers;
  extend offline scenarios with full review-to-completion orchestration,
  operational-summary publication, post-merge scanner freshness, and longer
  failure-recovery chains beyond the covered requeue/lifecycle flows
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

- [Documentation Home](index.md)
- [runbook.md](runbook.md)
- [Design library and current contracts (GitHub)](https://github.com/JustinMelger/ZeroOne-ops/blob/main/docs/design/README.md)
