# Legacy Dashboard Dependency and Retirement Audit

## Status and Scope

Completed documentation-only audit of repository revision `2272daa` on
2026-09-23. This is a retirement map, not authorization to remove support.
No commands, configuration, persisted state, tests, or runtime behavior change.

That statement describes the original audit. The subsequent implementation
status below records the completed extraction; the dependency table remains a
snapshot of the audited baseline rather than a claim that those imports persist.

## Shared Policy Extraction: Completed

The first follow-up is implemented and verified. `models.policy` now owns
`PolicySeverityEntry`, `PolicyIssueClassExclusionEntry`, and `PolicyView`.
Equivalent dashboard row names remain aliases, and `DashboardPolicyView` extends
the compact view with its legacy inventory field, retaining serialized shape.

`services/control_plane/policy/policy_view_builder.py` owns policy bootstrap and
compact presentation. It receives only bootstrap severities and has no provider,
repository, filesystem, or local run-state dependency. Both provider issue-policy
services and parsers use canonical policy types; issue policy no longer calls
`build([])` or requires a dashboard-item protocol. Workflow builders construct
the neutral builder for issue policy and retain the dashboard builder for legacy
routes. The dashboard builder delegates shared seeding/presentation and keeps
inventory counting, grouping, selection, and safety explanations.

The architecture contract forbids control-plane policy imports of dashboard
models/services, including indirect paths except one explicit retained edge:
`RunStateService` still composes `DashboardRunStateService`. Removing that legacy
state helper belongs to runtime retirement, not this extraction. This exception
does not permit a direct dashboard dependency in issue-policy code.

Verification: 187 focused policy/dashboard/workflow tests and 1,205 full-suite
tests passed, along with Ruff, formatting, architecture checks, mypy, and Bandit.
Characterization tests captured policy Markdown before extraction and verify
exact rendering and both provider parser round trips afterward. Wiring tests
reject dashboard builder/selector construction for issue policy and verify lazy
provider configuration loading.

No command, config, persisted-state contract, policy authority, or retirement
decision changed. Runtime removal and compatibility cleanup remain open.

The [GitLab issue control-plane contract](../functional/functional-design-gitlab-issue-control-plane.md#dashboard-support-window)
governs the support window. The [roadmap](../../roadmap.md) retains retirement as
open work. Existing remote dashboards remain readable history: this audit neither
migrates records nor labels, closes, rewrites, or deletes provider issues.

## Release Evidence

| Milestone | Repository evidence | Release containment |
| --- | --- | --- |
| Original two-minor-release promise | `2a739f12e6c65a056def59c7daa73f6dab4c57a5`, 2026-08-07, introduced the functional design's Dashboard Support Window | No local release tag contains this original development commit; do not use it alone as shipped evidence. |
| Promise shipped with issue control plane | `de34e31b9bd513e7f7bd46b48d6649201aa3ed01` (#318) contains the same promise | First containing tag `zeroone-ops-v0.53.0`, 2026-08-08. |
| Live rollout recorded complete | `778b4a97bb6d09360fcda68e5693a8b1f20b9bc6` (#339) removes the two-repository validation checkbox and adds live-validated issue-mode workflows to Implemented | First containing tag `zeroone-ops-v0.54.1`, 2026-08-14. |
| Issue mode becomes config default | `812e430` (#362) changes `GitLabConfig.control_plane_mode` to `issues` | First containing tag `zeroone-ops-v0.55.0`, 2026-08-17. |
| Subsequent minor releases | Local tags and [changelog](../../../CHANGELOG.md) | `0.56.0` (2026-08-20), `0.57.0` (2026-08-24), `0.58.0` (2026-09-14). |

The promise starts after implementation and live validation, not merely at
0.53.0. Counting two subsequent minor releases from the recorded rollout reaches
0.56.0; using the later default-mode release conservatively reaches 0.57.0.
Both have elapsed at this audit baseline. Patch release 0.54.1 is not counted as
a minor release.

The contract additionally requires removal in the next **planned breaking
release**. No removal authorization or target release follows from elapsed time.
The repository records validation completion but does not include deployment
inventories or a separately versioned maintenance-only announcement. Confirm
remaining operator usage and communicate the removal release before retirement.

Reproduction: inspect `git log --all -S 'two minor releases'` for the functional
design, `git show <commit>` for the promise/roadmap changes, and
`git tag --contains <commit> --sort=version:refname` for release containment.

## Dependency Dispositions

Paths in the table are relative to `src/zeroone_ops`; test references are relative
to `tests/zeroone_ops`. Grouped module stems enumerate related runtime units.
Classifications apply to the named behavior, not necessarily the entire file.

| Dependency | Classification | Consumers and evidence | Tests and retirement disposition |
| --- | --- | --- | --- |
| `cli.py`: `dashboard sonar`, `dashboard remediate`; `runner.py`: `sync_dashboard_sonar`, `dashboard_remediate` | Compatibility alias | Delegate to finding sync and remediation; commands use Typer deprecation and replacement warnings | `test_cli.py`, workflow and runner integration tests. Keep aliases separate from storage removal; do not remove the modern workflows they invoke. |
| `cli.py`: `dashboard reconcile`; `runner.dashboard_reconcile` | Compatibility alias with dashboard-only route | Unlike a transparent alias, it explicitly invokes legacy reconciliation and rejects GitLab issue mode | `test_cli.py`, `services/workflows/test_work_item_lifecycle_workflow.py`, dashboard integration. Decide removal/error guidance separately; do not silently retarget this command. |
| `cli.py`: `dashboard policy`; `runner.dashboard_policy` | Shared and requiring extraction of naming/routing | Not deprecated. Routes GitHub policy, GitLab issue policy, or dashboard policy; the combined GitLab job calls this public wrapper. There is no separate `policy` CLI group at this baseline | `test_cli.py`, `services/workflows/test_policy_workflow.py`, both provider policy suites. Preserve a working operator policy command; introduce/deprecate a neutral spelling explicitly before removing this name. |
| `models/config.py`: `GitLabConfig.control_plane_mode` | Dashboard-only mode selection in shared config | Literal `dashboard`/`issues`, default `issues`; workflow routing consumes it | `test_settings.py`, workflow routing tests. Removal must explicitly reject old `dashboard` settings with guidance, not silently switch authority. Preserve other GitLab settings. |
| `services/workflows/{finding_sync,remediation,recovery,policy,work_item_lifecycle}_workflow.py` legacy branches; runner factories | Dashboard-only branches inside shared orchestration | Construct dashboard client/service/runners only for the legacy route; modern routes share public wrappers and run context | `services/workflows/test_*_workflow.py`, `integration/dashboard/test_runner_dashboard.py`, `integration/test_dashboard_sync.py`. Remove only legacy branches after shared policy extraction; preserve lazy credentials, dry runs, summaries, and issue routes. |
| `providers/gitlab_dashboard_client.py`; `services/dashboard/dashboard_{service,parser,renderer}.py` | Dashboard-only | Native dashboard issue discovery, notes, schema/manifest parsing, merging, bounded sections, and whole-document writes | `providers/test_gitlab_dashboard_client.py`; dashboard service/parser suites and fixtures. Delete runtime only at retirement; retain historical documents and any fixtures still needed for persisted compatibility tests. |
| `services/dashboard/dashboard_policy_{service,processing_runner,acknowledgement_service}.py` | Dashboard-only | Apply policy to the dashboard document, process authorized notes, acknowledge commands | Corresponding dashboard policy tests and dashboard integration. Remove legacy orchestration, not shared authorization or neutral policy decisions. |
| `services/dashboard/dashboard_policy_action_service.py` and its action/type aliases | Compatibility alias/adapter | Wraps neutral `PolicyActionService` for dashboard notes and wording | `services/dashboard/test_dashboard_policy_action_service.py`. Remove wrapper with legacy callers; retain `services/control_plane/policy` action/processing code and tests. |
| `models/dashboard.py`: `DashboardPolicyState`, severity-state and issue-class-state aliases | Compatibility alias | Already aliases canonical `models.policy` types; imported by both issue parsers/services as well as dashboard code | Both provider policy contract/service suites, policy action tests. Move active imports to canonical types; do not delete the underlying policy state or change serialization. |
| `models/dashboard.py`: policy-view entries, `DashboardPolicyView`, `DashboardAutomationStatus`; `dashboard_policy_view_builder.py` | Shared and requiring extraction | Both provider issue services build policy views; the builder also owns config bootstrap seeding and legacy inventory/safety display | `services/dashboard/test_dashboard_policy_view_builder.py`, both issue-policy contract/service suites. Extract neutral bootstrap and issue-policy presentation; leave item inventory/safety display in compatibility code until removal. |
| `models/dashboard.py`: document, item, section, manifest, status/section normalization and MR aliases | Dashboard-only, with shared type leakage | Parser/renderer and legacy workflows use them; issue-policy builder protocols still accept `list[DashboardItem]` | Dashboard parser/service/normalizer suites. Remove only after issue-policy protocols no longer require dashboard items; preserve historical MR alias load tests where state compatibility remains. |
| `services/dashboard/dashboard_item_{selector,intake,normalizer}.py` | Dashboard-only with policy-builder dependency | Legacy remediation selects/normalizes rows; the policy-view builder constructs the selector for inventory safety display | Corresponding item tests and policy-view tests. Separate the neutral policy path first, then retire row selection and normalization. |
| `services/dashboard/dashboard_remediation_{runner,updater}.py` | Dashboard-only | Legacy execution orchestrates shared patch/validation/publication, updates rows, and local dashboard state | Corresponding runner/updater tests, dashboard integration. Remove legacy orchestration, retaining shared execution, validation, semantic safety, and publication tests. |
| `services/dashboard/dashboard_recovery_{command_parser,state,service,runner}.py` | Dashboard-only | Dashboard-scoped recovery commands, row transitions, polling, run summaries | Corresponding recovery tests. Retain issue-mode recovery authorization, receipts, and decision services under control plane; do not equate their command targeting with dashboard row targeting. |
| `services/dashboard/dashboard_reconciliation_{intake,service,runner}.py` | Dashboard-only | Reconcile row-linked MRs and update dashboard/state | Corresponding reconciliation tests. Remove only dashboard reconciliation; issue lifecycle remains authoritative for linked PR/MR terminal outcomes. |
| `services/intake/finding_dashboard_sync_service.py` | Dashboard-only | Legacy finding-sync projection creates/updates dashboard rows | `services/intake/test_finding_dashboard_sync_service.py`, legacy integration. Remove projection, preserve normalized finding collection and issue-mode reconciliation. |
| `services/intake/issue_intake.py`: `collect_dashboard_sync_issues`, result naming/messages | Shared and requiring extraction of naming | Every finding-sync route uses this collection path, including SonarQube/SARIF and managed-source metadata | `services/intake/test_sonar_dashboard_sync_service.py`, source tests and finding-sync integration. Rename separately with public/message compatibility decisions; never delete on the basis of dashboard terminology. |
| `services/workflows/{review_workflow,provider_workflow_builders}.py`; `services/review/pipeline/review_runner.py` | Shared and requiring removal of legacy wiring | GitLab runtime construction supplies a dashboard client; `_build_dashboard_updater` gates mirroring off in issue mode | Review workflow and `integration/review/test_runner_review.py`. Remove client tuple slot/constructor wiring only with callers updated; retain ordinary review and work-item projection. |
| `services/review/publish/review_dashboard_updater.py`; dashboard branch in `review_finalization_service.py` | Dashboard-only within shared finalization | Mirrors final review artifact into a row or standalone review-status entry; warning participates in review outcome handling | `services/review/publish/test_review_dashboard_updater.py`, review finalization and runner suites. Remove mirror/warning plumbing without altering issue projection repair, review publication, or continuity. |
| `services/dashboard/dashboard_run_state_service.py`; `RunStateService.dashboard` | Dashboard-only helper in shared composition | Constructed by shared run-state service; legacy runners use its selected/done/reopened/failed transitions | `services/shared/test_run_state_service.py`, dashboard integration. Remove helper/wiring, not the shared run-state service. |
| `models/state.py`: `DashboardItemState`, `AppState.dashboard_items`, `active_dashboard_item_id`, `RunRecord.dashboard_item_id`, `FailureStage.DASHBOARD_UPDATE` | Dashboard-only persisted compatibility | Local state loads through `StateStore`; old runs retain these values | `services/shared/test_state_store.py`, run-state and dashboard integration. Retain decode/round-trip compatibility until an explicit state-retention decision; runtime removal alone does not authorize dropping history. |
| `services/shared/run_summary_builder.py`, CLI `dashboard_item_id` output | Compatibility alias | Summary builder falls back from dashboard ID to work-item ID; old consumers may depend on output | Shared summary/runner and CLI suites. Decide output deprecation separately; preserve issue-mode `work_item_id`. |
| `models/remediation.RemediationWorkItem`, execution adapter/context union, materialization methods in remediation control plane and `remediation_work_item_promotion_service.py` | Dashboard-origin bridge in shared code; extraction/removal required | Dashboard normalizer produces the legacy target, dashboard runner invokes materialization; protocol and provider implementations still expose it | Remediation adapter/context/control-plane and promotion-service tests. Remove legacy target/method branches only after caller removal; retain `RemediationExecutionTarget`, issue-state adapters, and normal publish/link transitions. |
| `services/remediation/remediation_exclusion_service.py`; `AppState.remediation_exclusions` | Dashboard-only matcher and candidate dead legacy API | Service matches `DashboardItem`; no production construction reference found by symbol search, only its definition. Neutral issue policy uses its own exclusions | `services/remediation/test_remediation_exclusion_service.py`, state tests. Confirm unsupported external use before removal; retain historical state compatibility separately. Do not remove canonical policy exclusions. |
| Dashboard-related design documents, old examples/runbook sections, fixtures | Historical documentation or compatibility guidance | Design index already distinguishes history from current issue contracts | Keep historical banners and links; remove active installation guidance only with retirement. Preserve current template/config/review contracts even where test names retain dashboard terminology. |

The table covers all substantive modules in `services/dashboard`; its package
initializer can retire with the final module. Shared GitLab member/note
authorization and generic GitLab clients must survive: issue mode uses them too.
Operational summaries are derived issue-mode views, not legacy dashboards.

## Shared Policy Extraction Boundary

Both issue-policy services call the builder with an empty item list when
rendering. They need config-seeded canonical policy state, stable severity order,
disabled reasons, and excluded-class presentation, not dashboard row selection.
Keep exact current rendered output, policy command replay, authorization, and
bootstrap semantics in characterization tests before extraction.

The legacy builder additionally groups item inventory, computes matching counts,
and calls `DashboardItemSelector` with local state/filesystem context. Do not move
that entire dependency graph into the neutral issue-policy layer. Replace the
issue services' dashboard-item protocol dependency with a focused neutral view
contract; let the compatibility builder use shared seeding/presentation while
retaining its legacy inventory behavior until retirement.

## Compatibility and State Safeguards

- Configuration is strict. Removing a field or literal changes load behavior;
  old explicit dashboard mode needs a concise actionable error and release note.
  Do not repurpose dashboard configuration as implicit issue-mode consent.
  GitLab target branch, labels, assignees, remediation bootstrap severities and
  its supported-severities alias are not dashboard-only settings. Existing
  top-level validation-command migrations are unrelated to dashboard retirement.
- Command retirement is separate from mode retirement. `dashboard policy` is
  currently an active command, and `dashboard reconcile` is not a transparent
  alias despite its CLI description. Preserve these distinctions in tests.
- `StateStore.load()` validates historical JSON, while `save()` serializes the
  current model. Simply deleting fields can silently discard old history on a
  subsequent save. Retain compatibility fields/decoders in the first retirement
  slice or approve an explicit retention strategy before removal.
- Keep historical dashboard IDs, run failure stages, MR-name aliases, and review
  state normalization independently of active dashboard writes. Preserve current
  issue state, recovery history, review continuity, and publication retries.
- The current switch-and-sync contract does not migrate old policy overrides,
  linked work, or dismissal history. No automatic transfer, remote issue closure,
  or change to that cutover contract is proposed here.

## Ordered Follow-ups

1. **Shared dependency extraction (completed):** characterize policy bootstrap/rendering;
   extract neutral policy view types and builder behavior; replace active alias
   imports. Keep dashboard routing operational. Preserve provider-local transport
   and authorization. This prerequisite is distinct from consolidating duplicate
   GitHub/GitLab merge, intake, or finding-sync orchestration.
2. **Approved runtime retirement:** select and communicate a breaking release;
   confirm operator cutovers; remove dashboard-only routes, client, row services,
   review mirror, and legacy execution bridge. Reject explicit dashboard mode
   before provider writes. Preserve historical state loading and modern commands.
3. **Compatibility and documentation cleanup:** separately decide command alias
   deprecation/removal, neutralize remaining active names, update installation
   docs/examples, and preserve historical docs/state evidence. No broad history
   migration or provider cleanup job.

Each future code slice requires focused characterization tests plus Ruff,
formatting, architecture, mypy, Bandit, and the full suite. Preserve provider
policy contracts, workflow routing/dry runs, issue lifecycle/recovery, review
projection repair, shared remediation safety, and state compatibility tests.
Retire dashboard-only tests only alongside the corresponding approved behavior;
move shared assertions out of dashboard-named suites first.

## Audit Verification

Cross-checked imports, constructor wiring, command decorators, workflow branches,
policy render calls, persisted model fields, and matching unit/integration tests.
Release conclusions use local Git contents, tag ancestry, and the changelog,
not assumed deployment status. Checked documentation links and whitespace.
Runtime checks are intentionally not rerun for this documentation-only audit.

Ownership remains unchanged: finding sync owns inventory/policy projection,
remediation owns execution, lifecycle owns linked-request terminal state, and
labels remain indexes. Retirement stays open pending explicit approval.
