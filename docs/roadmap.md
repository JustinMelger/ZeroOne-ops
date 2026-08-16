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
- live-validated fresh-attempt recovery branch identity on GitHub and GitLab
- resilient multi-source SARIF intake: unavailable artifacts produce bounded
  diagnostics without blocking available sources or claiming stale
  reconciliation ownership
- operator-focused GitHub and GitLab work-item UX: location-disambiguated
  titles, concrete change-request summaries, durable bot-dismissal evidence,
  and intent-aware `fix` or `chore` change requests
- retired the repo-local dashboard feedback log; Notion plus provider-native
  issue and change-request evidence are the active operational feedback sources
- MLflow tracing support, Ruff pre-commit checks, and current CI workflows
- copyable GitHub Actions and GitLab CI control-plane installation templates

## Current Focus

### Operational Readiness

- [ ] design workflow-scoped preflight checks for repository config, required
  provider settings, reachable integrations, validation tools, and expected
  SARIF artifacts; keep them explicit, bounded, and free of remediation or
  lifecycle writes
- [ ] turn the GitLab CI example into a versioned end-to-end template contract:
  verify its scheduled/manual rules, job DAG, artifact wiring, resource groups,
  and merge-request review route in a representative GitLab fixture or test
  environment
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

### Finding Priority Semantics

- [ ] investigate SARIF tool-level severity versus workflow priority: confirm
  appropriate defaults for MyPy, Ruff, and future security-oriented sources;
  preserve raw SARIF levels as source evidence; and design bounded
  per-artifact mappings without fragmenting the shared promotion policy

### Trace Observability

- [ ] investigate and design MLflow trace correlation for repository, platform,
  ZeroOne run ID, workflow, change request, revision, and review/remediation
  stage; keep trace metadata bounded and avoid leaking secrets or raw operator
  context

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

### Remediation Source Neutrality

- [x] make remediation prompts, source profiles, and operator-facing labels
  source-neutral; retain SonarQube-specific wording only as source evidence

### Remediation Semantic Safety

- [ ] design a semantic-safety gate for rule-driven remediation: treat source
  diagnostics as evidence rather than instructions; require analysis to state
  current behavior, intended behavior, and local behavior-preservation evidence
  before auto-fix; require manual classification when that proof is unclear;
  prevent structured-edit generation from overriding the analysis decision

### Review Rollout

- [ ] live-validate same-SHA review-projection repair after a recoverable
  projection warning

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
- [design/functional/functional-design-finding-ingestion.md](design/functional/functional-design-finding-ingestion.md)
- [design/technical/technical-design-finding-ingestion.md](design/technical/technical-design-finding-ingestion.md)
- [design/functional/functional-design-finding-file-grouping.md](design/functional/functional-design-finding-file-grouping.md)
- [design/technical/technical-design-finding-file-grouping.md](design/technical/technical-design-finding-file-grouping.md)
- [design/functional/functional-design-work-item-state-projection.md](design/functional/functional-design-work-item-state-projection.md)
- [design/technical/technical-design-work-item-state-projection.md](design/technical/technical-design-work-item-state-projection.md)
- [design/technical/technical-design-github-platform-support.md](design/technical/technical-design-github-platform-support.md)
- [design/technical/technical-design-dashboard-remediation.md](design/technical/technical-design-dashboard-remediation.md)
- [design/functional/functional-design-remediation-recovery.md](design/functional/functional-design-remediation-recovery.md)
- [design/technical/technical-design-remediation-recovery.md](design/technical/technical-design-remediation-recovery.md)
- [design/functional/functional-design-pr-review-staged-pipeline.md](design/functional/functional-design-pr-review-staged-pipeline.md)
