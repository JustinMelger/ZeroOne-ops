# Post-V1 Code Cleanup Audit

## Scope And Status

This is a behavior-preserving maintenance track, audited on 2026-10-31. Each
slice is reviewed and merged before the next branch starts. Slices 1-3 are merged.
Slice 4 is implemented and verified, awaiting review and merge; slices 5-6 remain
proposals, not completed work.

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
| Deterministic overlap reconciler | No production callers; removed in slice 2 after transferring useful coverage. The active model-backed analysis service, prompt, and response models remain unchanged. | Continuity sequences use the real packet builder and analysis validator with explicit typed model responses. Packet uniqueness and final-artifact handoff are tested at their active boundaries; see the coverage map below. |
| Finding-sync storage base/batch contracts | Slice 3 consolidates one `FindingSyncStorage` protocol. Its canonical inventory loader retains strict live batch-aware discovery; the old four-index-only loader and unused storage lookup/upsert methods are removed. Active facade methods remain unchanged. | Native-adapter contract tests characterize ten-query order, scope/parser failures, exact snapshot retention, returned persistence authority, and transition ordering. Public sync, intake, execution, and offline provider scenarios retain broader behavior coverage. |
| Review workflow runner | Slice 4 moves linked evidence enrichment into an injected resolver and work-item lookup construction into the provider workflow builder. Continuity loading, same-SHA repair, and projection-factory construction remain for slice 5. | Preserve 48 pre-extraction characterization cases; cover lazy settings/client construction, exact handled errors and warnings, skipped routes, and real lookup over offline provider HTTP. Candidate/precision/artifact ownership remains unchanged. |
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

## Slice 2 Coverage Map

| Legacy scenario | Active coverage and disposition |
| --- | --- |
| New finding without candidates | The sequence suite supplies an empty prior pass and verifies the real packet and validated `new_in_this_pass` response. |
| One candidate retained as unresolved | Sequence scenarios verify explicit `still_unresolved` responses. A counterexample returns new/no-longer-present with one candidate, proving candidate count is not a deterministic decision rule. |
| Missing prior finding | The sequence suite supplies no current findings and verifies the explicit `no_longer_present` response. This is review continuity, not scanner-resolution proof. |
| Several candidates marked ambiguous | Ambiguous sequence coverage verifies both bounded candidate pairs and the scripted ambiguous response. A counterexample selects one valid prior and marks the other no longer present. |
| Repeated single-prior candidate deduplication | The packet-builder test verifies several matching signals produce one candidate pair. The old reconciler's deduplication algorithm is deleted, not copied into a fake. |
| Multi-pass unresolved/new/absent sequence | Existing sequence cases now call the live analysis service, not the removed deterministic implementation. The existing offline GitHub/GitLab repeated-review scenarios continue protecting native notes, inline reuse, state, and projection. |
| Wording, severity, region, and issue-kind drift; missing structured fields | Retain all sequence cases with independently declared candidate pairs and model outcomes. These assert bounded evidence and response handling, not model semantic accuracy. |
| Sibling helpers and same-title cross-file isolation | Retain packet assertions excluding unsupported candidate pairs and explicit new/no-longer-present responses. |
| Historical identity continuity | A sequence case passes a legacy identity through real packet construction and validated analysis; existing prior-note parser and identity tests remain. |
| Result validation and artifact meaning | Expand index, malformed-shape, and candidate-boundary rejection tests; preserve prior-SHA, duplicate-reference, backend-unavailable, and model-error coverage. The reconciliation test no longer mocks overlap analysis and checks continuity, candidate lineage, evidence, and classification through artifact construction. |

The local sequence script accepts one expected packet and returns one explicit
typed response. It rejects extra, unused, and mismatched requests. It never
computes an outcome from candidate count or matching heuristics. All new cases
replace the model-client boundary and bypass credential loading; they do not
add live calls or a production injection API.

## Retained Compatibility And Boundaries

- Keep public provider result aliases, historical state/identity decoding,
  intentional provider differences, and existing read-before-write limitations.
- Keep thin shared-renderer, intake, recovery, lifecycle, and projection wrappers.
- Finding sync owns inventory and policy/capacity projection; remediation owns
  execution and linked requests; lifecycle owns terminal request reconciliation.
- Labels remain indexes; persisted issue machine state remains authoritative.
- Leave historical dashboard records, folder layout, product changes, and
  concurrency hardening outside this track. Untracked duplicate copies and the
  retired prompt were separately removed at the operator's request after slice 2;
  that housekeeping was not a tracked runtime change.

## Slice 3 Storage Contracts

The storage-specific lookup/upsert forwarding tests are retired with their
unused methods; provider-facade dismissal and unchanged-detection tests remain.
The old four-query mock factory has no remaining consumers and is removed.
Storage tests instead use the existing paired native-client harness with real
parsers, renderers, facades, and adapters. No new production test seam is added.

Before extraction, 44 native-adapter characterization tests passed against the
live `load_batch_inventory()` path. Those same tests now exercise canonical
`load_inventory()` with identical queries and outcomes. Additional pure guard
tests check returned object identity, input non-mutation, and caller messages.
The complete guard is applied only to exact reads and listings; create-response
validation and the native snapshot store remain unchanged. The technical
[state-projection design](technical-design-work-item-state-projection.md)
describes the canonical boundary.

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

Slice 1 boundary review: only unused paths, imports, and duplicate eligibility naming were
removed. The active shared services and provider adapters retain all decisions,
state ownership, persistence order, and compatibility behavior. No live provider
validation or deployment was performed for this maintenance slice.

Slice 2 verification passed: 84 continuity/reconciliation tests before deleting
the obsolete implementation, then 342 focused review/client/offline-scenario
tests and 2,330 full-suite tests with 91.12% coverage. Ruff, formatting,
architecture, mypy, Bandit, strict documentation build, and `git diff --check`
also passed. Source/test/CI reference checks found no imports of the deleted
module; historical designs and the active overlap prompt remain unchanged.

Slice 2 boundary review: the only production-code change deletes an unused
module. Packet construction, model-backed outcome selection, structural
validation, continuity attachment, and artifact construction retain their
existing ownership and behavior. No prompt, schema, configuration, provider
transport, or fallback changed. Scripted outcomes demonstrate wiring and
validation, not semantic accuracy; no live model/provider validation was run.

Slice 3 verification passed: 44 native-adapter characterization tests before
extraction, then 1,522 focused storage/sync/intake/remediation/offline-scenario
tests and 2,363 full-suite tests with 91.04% coverage. Ruff, formatting,
architecture, mypy, Bandit, strict documentation build, and `git diff --check`
passed. No source/test/CI references to the retired protocol or loader remain.

AST comparisons confirm unchanged discovery, normalization, rediscovery, provider
create/update/close/reopen, payload validation, and snapshot-normalization bodies.
Coordinator, creation, and guarded-projection bodies differ only by canonical
contract names. The scope guard retains the same condition and error messages;
its tests cover original-object return, input non-mutation, and parser-error
propagation. Create-response parsing and the native snapshot store are unchanged.

Slice 3 boundary review: inventory discovery and scope validation stay shared;
providers retain parsing, transport, native snapshots, and persistence-response
normalization. Policy, capacity, lifecycle, remediation execution, reporting,
and provider-specific unchanged detection retain their existing ownership.
No configuration, schema, operator commands, additional reads/writes, retry
policy, or concurrency guarantee changed. No live provider validation was run.

Slice 4 verification passed: 48 pre-extraction characterization cases, then
1,381 focused context/review/workflow/work-item/client/offline-scenario tests
and 2,450 full-suite tests with 91.13% coverage. Ruff, formatting, architecture,
mypy, Bandit, strict documentation build, and `git diff --check` passed.
Resolver tests cover lazy settings/client construction, exact exception and
warning boundaries, historical evidence, input preservation, and evidence
clearing. Paired offline scenarios use real provider lookup/parsing over fake
HTTP and cover ambiguous linkage and handled lookup failure without stopping
review. Dry-run, no-selection, context-failure, and same-SHA routes perform no
context lookup.

Slice 4 boundary review: the resolver owns exact-link evidence enrichment;
workflow composition owns lazy provider lookup construction and normalization.
The existing review logger retains warnings. Candidate generation, precision,
artifact meaning, publication, and projection retain their previous ownership.
AST comparisons confirm unchanged runner sequencing except for delegation,
unchanged continuity/projection methods, and the same handled exceptions and
warning call. No prompts, schemas, persisted state, provider read counts, or
concurrency guarantees changed. No live model/provider calls were made;
continuity and same-SHA repair extraction remain slice 5.
