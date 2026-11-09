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
- [ ] verify the next generated release PR updates the local `uv.lock` package
  version alongside `pyproject.toml`, without changing dependency versions;
  the targeted Release Please TOML updater is configured and locally exercised

### Review Overview Design

The [functional design](https://github.com/JustinMelger/ZeroOne-ops/blob/main/docs/design/functional/functional-design-review-overview.md)
and [technical design](https://github.com/JustinMelger/ZeroOne-ops/blob/main/docs/design/technical/technical-design-review-overview.md)
separate a persistent PR/MR overview from review-pass authority, inline findings,
and optional structured CI evidence. Slice 1 implementation has automated offline
verification; live acceptance remains pending.
Its single bot-owned overview retains two complete passes and five summaries
independently of model-context limits, separates failed attempts, and enforces a
60,000 UTF-8 byte budget with ownership and read-before-write guards. Reporting
and evidence-only refresh remain proposed, not implemented. Model judgment is
unchanged. Automated completion does not close the separate live gates below.
Unconfigured quality reporting has no empty section or upfront notice; the AI/CI
disclaimer appears in the overview footer.
The verdict is prioritized above findings; exact commit metadata and follow-up
provenance are collapsed into Review Details without changing review authority.
Linked findings avoid repeating inline reasoning; unlinked findings retain full
details. Shared presentation preserves punctuation without activating Markdown/HTML.
The overview uses one verdict heading; unmatched prior concerns are described as
not reported, not verified fixes. Publication guards reject blank GitLab identity
and withhold projection on failed request/head revalidation after inline writes.
Reviewed commit labels now combine a short SHA with optional provider-supplied
titles, persisted per pass and reused without model calls or metadata backfill.
Live commit-label presentation acceptance remains unchecked.
The bounded **What Changed** implementation carries descriptive output from the
existing candidate call into completed artifacts without forwarding it as
precision or overlap evidence. Live description quality is not established by
the offline scripts.
Offline regressions cover GitHub installation-token identity and withholding
projection repair when overview authority is conflicting or unavailable.
The **Earlier Findings** implementation preserves up to ten distinct overview-only
concerns independently of complete snapshot retention, labels resolution as
unverified, and discloses retention evictions. Automated verification passed;
live GitHub/GitLab presentation acceptance remains separate.
Deleted-overview recreation on a new head now uses verified request-scoped cache
when available and discloses unavailable/partial history otherwise. Automated
verification of this recovery follow-up passed; live acceptance remains separate.
Overview presentation now shares defensive browser-link validation with Earlier
Findings retention, preserving reasoning when stored URL text is malformed.
Keep live acceptance separate and complete it before report integration; validate
the smallest JUnit installation before expanding to coverage.

- [x] review the proposed contracts before implementation
- [x] slice 1: persistent overview, durable bounded history, stale-write guards,
  and existing same-SHA/inline/projection-repair continuity
- [x] **Pre-merge: Earlier Findings visibility (automated)**: preserve operator-readable
  evidence and reviewed SHA for overview-only concerns not reported again,
  explicitly label **Resolution not verified**, and define bounded retention and
  eviction behavior. Covered successive passes, fresh-workspace recovery,
  reuse/repair/restoration, escaping, and the complete payload budget; absence
  in a later finding list never establishes resolution
- [ ] live-validate **Earlier Findings** presentation and persistence on GitHub
  and GitLab separately from automated completion
- [x] review and implement the bounded **What Changed** follow-up: a separate
  factual reviewed-diff summary generated within an existing model call,
  persisted with complete artifacts and preserved during reuse and recovery
- [ ] live-validate **What Changed** description quality on GitHub and GitLab;
  scripted offline tests establish propagation and isolation, not factual quality
- [x] **UX slice: Reviewed Commit Context**: show a short linked SHA and the
  provider-supplied commit title; collapse full head/base details, persist
  optional pass metadata, and cover lookup failures, exact-SHA matching,
  historical compatibility, and reuse/recovery without additional model calls
- [ ] live-validate reviewed commit labels on GitHub and GitLab separately from
  automated verification
- [ ] live-validate slice 1 on GitHub and GitLab, including fresh-workspace and
  partial-publication recovery, before starting slice 2
- [ ] slice 2: CI-provided JUnit reports, producer correlation, and same-SHA
  quality refresh without additional model calls
- [ ] validate minimal JUnit installation examples and live evidence refresh on
  both providers before starting slice 3
- [ ] slice 3: Cobertura line coverage, comparable head/base reports, and
  changed-code coverage with explicit availability states
- [ ] live-validate GitHub and GitLab overview updates, report wiring, and recovery
  separately from automated completion

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
