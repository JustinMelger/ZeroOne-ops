# Post-V1 Code Cleanup Audit

## Scope And Status

This is a behavior-preserving maintenance track, audited on 2026-10-31. Each
slice is reviewed and merged before the next branch starts. Slice 1 is implemented
and verified, awaiting branch review and merge; slices 2-6 remain proposals, not
completed work.

No configuration, persisted schema, command, prompt, workflow decision, or
operator output changes are intended. The [roadmap](../../roadmap.md) owns the
short execution checklist. The ignored local restructuring notes are optional
contributor context, not a dependency of this document.

## Dependency Inventory

| Dependency | Production consumers and disposition | Coverage and replacement |
| --- | --- | --- |
| `FindingPromotionCapacityService` and its plan | No live callers; the active batch planner imported only `DEFAULT_SOURCE_PRIORITY`. Remove the superseded service and move the unchanged value `100` to `models.policy`. | Transfer useful severity, identity, remaining-capacity, and source-priority scenarios to `test_finding_batch_promotion_service.py`. The Sonar pagination regression now uses the active planner. |
| `FindingPolicyReconciliationService` and its decision model | No live callers; current sync uses `FindingBatchReconciliationService` for both singles and batches. Remove the old implementation. | Add single-record characterization for policy/capacity transitions, protected work, complete-inventory absence precedence, unavailable inventories, and input immutability to `test_finding_batch_reconciliation_service.py`. |
| Shared change-request lookup module | Its factory and concrete adapters are referenced only by their own tests. Remove the module and those delegation-only tests. | Keep active publication, branch-revision lookup, provider-client, revision, and publication-retry tests. No active lookup interface is replaced. |
| GitLab recovery-service workflow factory | No callers; the active GitLab recovery workflow already composes recovery independently. Remove only the unused factory and its now-unused imports. | Retain GitLab recovery service, runner, workflow, authorization, replay, and command-processing coverage. |
| `utils.command.repo_root()` | No production or test callers; only returns the current directory. Remove the unused module. | No replacement abstraction; existing repository-root ownership remains unchanged. |
| Internal remediation-eligibility wrapper | Production uses the canonical eligibility entrypoint; internal batch tests used a second name for the same checks. Inline those checks into the canonical function and update test imports. | Keep intake, claimed revision, path-safety, and provider-parity tests on the canonical entrypoint. |
| Deterministic overlap reconciler | No production callers; continuity sequence tests still exercise this old algorithm. Defer removal to slice 2. | Move useful cases to the active packet builder, model-backed overlap service, and result validator with scripted responses. Never substitute the old algorithm for model-backed production decisions. |
| Finding-sync storage base/batch contracts | Active sync uses batch-aware discovery; old storage inventory, source lookup, and upsert methods have only test consumers. Defer narrowing and consolidation to slice 3. | Preserve native snapshots, indexed discovery, uncertain-write rediscovery, actual persistence responses, warnings, ordering, and provider parity. Facade methods with similar names remain active. |
| Review workflow runner | Active, but also owns provider construction, linked evidence loading, continuity loading, and same-SHA repair. Extract responsibilities in slices 4-5. | Characterize verified linkage and add same-SHA reuse/projection-repair scenarios before extraction. Preserve candidate/precision/artifact ownership. |
| Remediation work-item runner | Active, but combines ordinary execution, recorded publication retry, revision preparation, and outcome projection. Extract narrowly in slice 6. | Add offline retry/revision scenarios first. Preserve recorded scope, retry precedence, checkout-before-context, rollback, and request reuse. |

Reference searches cover source imports, construction sites, tests, and tracked
documentation. Dedicated tests are not evidence that an implementation remains
part of a live workflow. Conversely, a compatibility name alone is not evidence
that code is dead.

The current planner deliberately differs from the superseded planner in ownership
conflict handling and batching units. Characterization protects the current live
behavior; it does not restore obsolete behavior to make old tests pass. Existing
duplicate-owner, dismissal, policy, and deferred-work tests remain authoritative.

## Ordered Follow-Ups

1. Remove superseded intake and unused scaffolding; retain current behavior.
2. Align continuity tests with production, then delete the unused reconciler.
3. Narrow finding-sync storage and share parsed-state scope validation, not CRUD
   transport or a generic provider strategy.
4. Extract verified review-context resolution and compose provider dependencies
   outside the review runner while preserving lazy credential loading.
5. Extract continuity/reference loading and same-SHA reuse/repair coordination
   after protecting those flows with offline scenarios.
6. Extract recorded-publication-retry coordination and verified revision
   preparation after protecting both routes with offline scenarios.

## Retained Compatibility And Boundaries

- Keep public provider result aliases, historical state/identity decoding,
  intentional provider differences, and existing read-before-write limitations.
- Keep thin shared-renderer, intake, recovery, lifecycle, and projection wrappers.
- Finding sync owns inventory and policy/capacity projection; remediation owns
  execution and linked requests; lifecycle owns terminal request reconciliation.
- Labels remain indexes; persisted issue machine state remains authoritative.
- Leave the untracked legacy prompt, historical dashboard records, folder layout,
  product changes, and concurrency hardening outside this track.

## Verification

Before removing the superseded services, the expanded active planner and
reconciliation suites passed: 130 tests. Each implementation slice additionally
requires focused suites, Ruff, formatting, architecture, mypy, Bandit, full pytest,
and a workflow-boundary review before its roadmap item is checked.

Slice 1 verification passed: 1,075 focused intake/control-plane/workflow tests,
2,310 full-suite tests with 90.95% coverage, Ruff, formatting, architecture, mypy,
Bandit, strict documentation build, and `git diff --check`. Reference searches
found no remaining source/test imports of the removed paths. An AST comparison
confirmed canonical eligibility preserves the former implementation exactly.

Boundary review: only unused paths, imports, and duplicate eligibility naming were
removed. The active shared services and provider adapters retain all decisions,
state ownership, persistence order, and compatibility behavior. No live provider
validation or deployment was performed for this maintenance slice.
