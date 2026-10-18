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

- consistent seven-day Renovate/uv cooldown for all normal PyPI updates,
  including operator-approved major upgrades

- v1 configuration alias retirement: canonical platform and remediation fields
  only, with strict field-specific replacement errors and manual migration
  guidance

- removed unused legacy branch/severity helpers and Python compatibility
  accessors; no-op review settings now fail strict validation with v1 removal
  guidance, preserving historical serialized-field compatibility

- validation evidence in new remediation PR/MR descriptions independently of
  feedback mode, distinguishing passed checks, preserved baseline, no commands,
  and unavailable evidence without exposing raw output
- v1 dashboard runtime and command retirement: GitHub/GitLab issue mode only,
  neutral `policy run`, explicit local-history cleanup safeguards, and preserved
  review continuity; [migration guide](migration-v1.md)

- shared GitHub/GitLab post-authorization recovery command processing,
  preserving provider-local discovery, authorization, replay semantics,
  authoritative persistence sequencing, and dry-run simulation

- shared GitHub/GitLab finding-sync orchestration with normalized storage
  adapters, preserving reconciliation order, warning behavior, and dry runs

- shared GitHub/GitLab remediation intake coordination over normalized records,
  preserving selection, claims, dry runs, and provider-native result contracts

- provider-neutral authoritative work-item state merging and finding-sync result,
  with provider compatibility imports and existing omission/clearing semantics
  preserved

- source-focused daily finding dogfood with explicit manual test MyPy publication
  under a separate namespace and scanner-failure gating before finding sync

- shared policy presentation and bootstrap extracted into neutral models and a
  pure builder for GitHub/GitLab issue policy

- completed the [legacy dashboard dependency and retirement audit](design/technical/technical-audit-legacy-dashboard-retirement.md)
  and implemented its v1 runtime-removal follow-up
- complete paginated SonarQube intake with per-source failure isolation:
  incomplete inventories never resolve existing work as missing

- dismissal-aware promotion capacity: indexed closed and open dismissals are
  suppressed before source/severity ranking on GitHub and GitLab

- GitLab and GitHub staged change-request review with continuity, concise
  developer-facing notes, and bounded inline comments
- provider-neutral normalized finding ingestion with SonarQube and SARIF/Ruff
  adapters
- bounded per-artifact SARIF severity mappings with raw levels retained as
  source evidence; MyPy dogfood maps its broad error output to medium priority,
  while unmapped artifacts retain generic SARIF mapping
- GitHub and GitLab issue control planes: policy issue, authoritative work-item
  issues, recovery commands, lifecycle reconciliation, and derived operational
  summaries
- live-validated GitLab issue-mode policy, remediation, recovery, lifecycle,
  dismissal suppression, blocked-work handling, stale-claim recovery, and the
  derived operational summary
- shared remediation execution, validation setup/check commands, provider-local
  change-request publishing, and bounded branch naming
- remediation-owned `validation_setup_commands` and `validation_commands`
  configuration
- live-validated opt-in baseline-aware validation feedback on GitHub and
  GitLab issue-mode repositories: clean validation, preserved baseline
  failures, one-file correction feedback, compact work-item evidence,
  provider-native change-request validation summaries, and unscoped-regression
  blocking
- live-validated shared promotion capacity for GitHub and GitLab issue-mode
  repositories, with a configurable active-work limit and aggregate capacity
  backlog visibility
- reversible policy and capacity reconciliation for GitHub and GitLab issue
  mode: protected work stays active, while eligible unlinked work can move
  between open coordination and closed deferred backlog
- configurable source promotion priorities for GitHub and GitLab issue mode:
  policy-eligible work ranks by stable source ID before normalized severity
  and finding identity, while active `approved` and `in_progress` work remains
  protected and unspecified sources share a neutral default priority
- complete-inventory stale reconciliation: absent exact findings close as
  `no_longer_detected` before policy evaluation, with location-bound identity
  documented until occurrence-aware reconciliation is designed
- GitHub live validation from Ruff finding to remediation pull request, review
  projection, merge, and terminal work-item closure
- GitLab/GitHub closed-unmerged convergence: preserve traceability, block
  automatic retries, and require a later explicit operator recovery action
- runner composition split into focused finding-sync, remediation, recovery,
  lifecycle, policy, and review workflows while preserving public commands
- remediation safety hardening: exact declared/parsed patch-path matching,
  strict repository-config validation, release-pinned operational templates,
  and documented execution-trust boundaries
- bounded dirty-workspace remediation diagnostics: preserve the safe
  pre-branch guard while showing tracked or untracked paths and clear cleanup
  guidance in provider work-item evidence
- remediation runtime-workspace ownership: exact configured untracked state,
  SARIF, and solution-output paths no longer block branch preparation, while
  tracked, staged, renamed, or unconfigured workspace changes remain protected
- validation-setup failure guidance in GitHub and GitLab work items: preserve
  the failed command, exit code, and workflow-log link while directing
  operators to likely toolchain, lockfile, registry, or authentication causes
  without persisting command output
- live-validated fresh-attempt recovery branch identity on GitHub and GitLab
- resilient multi-source SARIF intake: unavailable artifacts produce bounded
  diagnostics without blocking available sources or claiming stale
  reconciliation ownership
- configured SARIF artifact source IDs are canonical durable namespaces, while
  scanner-reported tool identities remain provenance
- operator-focused GitHub and GitLab work-item UX: location-disambiguated
  titles, concrete change-request summaries, durable bot-dismissal evidence,
  and intent-aware `fix` or `chore` change requests
- source-neutral remediation prompts and operator-facing labels, with
  SonarQube-specific terminology retained only as source evidence
- retired the repo-local dashboard feedback log; Notion plus provider-native
  issue and change-request evidence are the active operational feedback sources
- optional MLflow workflow root traces for live review and remediation, with
  repository, platform, run, workflow, work-item, change-request, outcome,
  and validation-outcome correlation; plus Ruff pre-commit checks and current
  CI workflows
- copyable GitHub Actions and GitLab CI control-plane installation templates
- versioned GitLab CI installation template contract: release-pinned image,
  structured job-DAG and security-boundary checks, and a matching GitLab
  issue-mode configuration fixture
- mandatory structural semantic-safety gate with bounded analysis claims,
  operator evidence, and verified review-context handoff; structural validation
  does not establish semantic correctness
- operator-controlled GitHub/GitLab same-request review-feedback revisions,
  verified checkout before context construction, one-use command receipts,
  claim exclusion, failure evidence, and persisted projection repair;
  live rollout validation remains below
- live-validated same-SHA review-projection repair after a recoverable warning

## Current Focus

### Remediation Batching

- [x] review the [proposed functional contract](design/functional/functional-design-remediation-batching.md)
  for default-ten promotion-time file/rule batches in new work items only,
  preserving existing issues and one-file execution with no partial publication
- [x] review the [proposed technical contract](design/technical/technical-design-remediation-batching.md)
  for frozen member state, shared planning, complete execution coverage, and
  the existing scan-before-sync pipeline contract without new freshness gates
- [x] slice 1 - models and planning: optional batch state/configuration, frozen
  membership, identity, ownership, grouping, ranking, and capacity tests;
  preserve existing single-finding behavior
- [ ] slice 2 - finding sync and projection: member observations, policy/capacity
  deferral, absence reconciliation, safe creation, and GitHub/GitLab parity
- [ ] slice 3 - execution and recovery: complete context and analysis coverage,
  one-file edits, validation, retry/revision evidence, and recovery precedence
- [ ] slice 4 - operator UX and rollout: issue rendering, summaries, integration
  verification, and live GitHub/GitLab validation before the batching candidate

Use a separate reviewable branch per slice and create its detailed implementation
plan when picked up. Keep batch creation disabled until the end-to-end path is
ready; the designs above own the detailed contracts. Slice 1 is a dormant
foundation; end-to-end batching is not implemented or enabled.
Validate the current `main` release candidate first, then a batching candidate;
publish stable v1 only after both validation rounds and any required fixes pass.

### V1 Release Readiness

- [x] retire legacy GitLab dashboard runtime and commands with migration guidance
- [ ] confirm remaining GitLab installations have completed issue-mode cutover
  and local-state cleanup before tagging v1

- [ ] document the derived-image toolchain contract for validation: retain the
  thin non-root base image with Git, curl, and CA certificates; document how
  operators extend it for language-specific tools without changing the
  ZeroOne Ops image contract
- [ ] live-validate same-request revisions and failure recovery on GitHub and GitLab
- [ ] smoke-test manual merge-conflict recovery on both providers: close the
  conflicted PR/MR, reconcile its work item to `blocked`, then explicitly
  requeue a policy-eligible fresh attempt

Review-feedback design: [functional contract](design/functional/functional-design-remediation-review-feedback.md)
  and [technical remediation review feedback](design/technical/technical-design-remediation-review-feedback.md)

V1 uses the existing manual recovery path rather than automatic merge-conflict
detection or rebasing. After a failed revision push in a reused workspace,
retry from a fresh checkout; automatic local-branch recovery remains post-v1.

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
  are background, not prerequisites for the promotion-time batching proposal
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
