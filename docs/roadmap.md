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

- GitLab and GitHub staged change-request review with continuity, concise
  developer-facing notes, and bounded inline comments
- provider-neutral normalized finding ingestion with SonarQube and SARIF/Ruff
  adapters
- bounded per-artifact SARIF severity mappings with raw levels retained as
  source evidence; MyPy dogfood maps its broad error output to medium priority,
  while unmapped artifacts retain generic SARIF mapping
- GitLab dashboard control plane with Maintainer/Owner-authorized policy
  commands, remediation, review projection, and lifecycle reconciliation
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

## Current Focus

### Operational Readiness

- [ ] define the derived-image toolchain contract for validation: retain the
  thin non-root base image with Git, curl, and CA certificates; document how
  operators extend it for language-specific tools without changing the
  ZeroOne Ops image contract
- [ ] add end-to-end scenario fixtures that span normalized intake, policy,
  remediation, provider-native change requests, lifecycle reconciliation, and
  derived summaries for both GitHub and GitLab issue mode
- [ ] design a stable machine-readable run-summary output alongside the current
  human CLI summary, including selected finding, policy decision, validation
  outcome, change-request reference, lifecycle transition, and bounded error
  evidence

### Remediation Review Feedback

- [ ] design and investigate a GitHub/GitLab remediation review-feedback loop:
  a projected `findings_present` result must become an explicit actionable
  state, preserve the linked change request and review evidence, and define
  bounded automatic versus operator-command rework without treating it as a
  normal fresh remediation claim; reuse the work-item state-projection boundary
  for provider issue-state rendering

### Remediation Mergeability

- [ ] design GitHub/GitLab handling for remediation change requests that become
  unmergeable because of merge conflicts: detect the provider-native state,
  preserve the linked request and conflict evidence, move the work item to an
  explicit recoverable state, and give operators a clear requeue, dismiss, or
  manual-resolution path without automatic rebases or force-pushes

### Remediation Semantic Safety

- [x] define mandatory semantic-safety analysis and terminal manual handling
- [ ] implement the shared semantic-safety gate, bounded provider evidence, and
  analysis/structured-edit contracts before the remediation feedback loop
- design: [functional semantic safety](design/functional/functional-design-remediation-semantic-safety.md)
  and [technical semantic safety](design/technical/technical-design-remediation-semantic-safety.md)

### Review Rollout

- [x] live-validate same-SHA review-projection repair after a recoverable
  projection warning

### Review Finding Clarity

- [ ] define and enforce a bounded self-contained finding contract: every
  actionable finding states the affected behavior, concise causal impact,
  scoped fix, and relevant locations; require an expanded causal walkthrough
  only for cross-flow or behavior-sensitive changes, not routine local issues

### Review Summary UX

- [ ] design GitHub/GitLab mutable review summaries: maintain one current
  provider comment per change request, guarded by reviewed revision so an
  older run cannot overwrite newer results; retain line-level comments and
  durable continuity evidence separately rather than creating a new visible
  summary comment for every run

### Review Configuration

- [ ] design shared glob-pattern semantics for `review.supported_paths` and
  `review.ignored_paths`, applied consistently to changed-file selection and
  helper-following context while preserving repository-relative path safety
- [ ] design optional provider-native remediation reviewer assignment: support
  configured reviewer lists after change-request creation or reuse, keep
  GitHub users/teams and GitLab user-ID resolution explicit, and retain
  best-effort assignee behavior independently

## Parked For Later

- external API/database-backed control plane
- additional structured finding adapters and a later shared cross-source
  reconciliation/deduplication stage
- richer developer feedback consumption for review notes and broader review
  evaluator growth
- multi-file remediation and automated test-repair workflows
- broader dashboard/history presentation improvements after operator usage
  establishes the need
- retire GitLab dashboard mode after two maintenance-only minor releases
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
- deterministic file-level finding inventories and a later remediation-unit
  boundary; preserve individual findings and provenance without treating a file
  group as one automatic remediation
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
- [design/functional/functional-design-work-item-state-projection.md](design/functional/functional-design-work-item-state-projection.md)
- [design/technical/technical-design-work-item-state-projection.md](design/technical/technical-design-work-item-state-projection.md)
- [design/functional/functional-design-remediation-recovery.md](design/functional/functional-design-remediation-recovery.md)
- [design/technical/technical-design-remediation-recovery.md](design/technical/technical-design-remediation-recovery.md)
- [design/functional/functional-design-pr-review-staged-pipeline.md](design/functional/functional-design-pr-review-staged-pipeline.md)
