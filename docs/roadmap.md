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
- live-validated opt-in baseline-aware validation feedback on GitHub and
  GitLab issue-mode repositories: clean validation, preserved baseline
  failures, one-file correction feedback, compact work-item evidence,
  provider-native change-request validation summaries, and unscoped-regression
  blocking
- live-validated shared promotion capacity for GitHub and GitLab issue-mode
  repositories, with a configurable active-work limit and aggregate capacity
  backlog visibility
- GitHub live validation from Ruff finding to remediation pull request, review
  projection, merge, and terminal work-item closure
- GitLab/GitHub closed-unmerged convergence: preserve traceability, block
  automatic retries, and require a later explicit operator recovery action
- runner composition split into focused finding-sync, remediation, recovery,
  lifecycle, policy, and review workflows while preserving public commands
- remediation safety hardening: exact declared/parsed patch-path matching,
  strict repository-config validation, release-pinned operational templates,
  and documented execution-trust boundaries
- MLflow tracing support, Ruff pre-commit checks, and current CI workflows
- copyable GitHub Actions and GitLab CI control-plane installation templates

## Current Focus

### Work-Item UX

- [ ] distinguish same-rule, same-file findings in GitHub and GitLab work-item
  titles with a compact source location; retain separate stable identities and
  branches, and defer any many-findings-per-file grouping design
- [ ] refine generated change-request descriptions around operator decisions:
  require the existing proposal summary to explain the concrete edit and why;
  remove generic structured-edit provenance; retain concise scope and validation
  evidence that helps review, merge, or recovery decisions
- [ ] persist and render compact execution evidence for bot-dismissed work
  items on GitHub and GitLab: decision summary, stage, run reference, and safe
  recovery guidance without copying raw model or command output into the issue
- [ ] make remediation branch and change-request prefixes reflect normalized
  remediation intent: keep `fix` for behavioral defects, use an appropriate
  neutral prefix for test, typing, lint, or maintenance-only edits, and define
  a stable fallback without deriving commit semantics from raw source wording

### Finding Intake Resilience

- [ ] isolate configured SARIF artifact failures so available sources continue
  to sync; record bounded per-artifact diagnostics and never stale-reconcile an
  unavailable source as an authoritative empty inventory

### Policy Reconciliation

- [ ] reconcile unlinked candidate work items that become policy-ineligible
  into a non-cluttering terminal or hidden policy-deferred state on GitHub and
  GitLab; preserve protected active work and aggregate backlog visibility, then
  define the re-enable behavior explicitly

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
  normal fresh remediation claim

### Remediation Mergeability

- [ ] design GitHub/GitLab handling for remediation change requests that become
  unmergeable because of merge conflicts: detect the provider-native state,
  preserve the linked request and conflict evidence, move the work item to an
  explicit recoverable state, and give operators a clear requeue, dismiss, or
  manual-resolution path without automatic rebases or force-pushes

### Remediation Source Neutrality

- [ ] audit remediation prompts, source profiles, context labels, and remaining
  SonarQube-era naming against SARIF and future normalized sources; retain only
  deliberate source-specific guidance and make generic remediation semantics
  explicit in tests

### Remediation Semantic Safety

- [ ] design a semantic-safety gate for rule-driven remediation: treat source
  diagnostics as evidence rather than instructions; require analysis to state
  current behavior, intended behavior, and local behavior-preservation evidence
  before auto-fix; require manual classification when that proof is unclear;
  prevent structured-edit generation from overriding the analysis decision

### Documentation Cleanup

- [ ] retire the repo-local dashboard feedback log as an active reference after
  preserving any still-relevant historical decisions; update design references
  to use issue-mode evidence and Notion feedback without changing legacy
  dashboard runtime compatibility

### Phase 7: Recovery Rollout

- [ ] implement and live-validate fresh-attempt branch identity on GitHub and
  GitLab
- design: [functional recovery contract](docs/design/functional/functional-design-remediation-recovery.md)
  and [technical implementation plan](docs/design/technical/technical-design-remediation-recovery.md)

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
- move remediation validation setup/check commands into a remediation-owned
  configuration block after rollout feedback confirms the current contract
- consider an argv-style alternative to shell-based validation commands after
  the executable-CI-policy trust model has been live-reviewed
- make MLflow tracing an optional package extra after tracing rollout feedback
  confirms the supported installation profile

## Reference Docs

- [README.md](README.md)
- [runbook.md](runbook.md)
- [design/functional/functional-design-finding-ingestion.md](design/functional/functional-design-finding-ingestion.md)
- [design/technical/technical-design-finding-ingestion.md](design/technical/technical-design-finding-ingestion.md)
- [design/technical/technical-design-github-platform-support.md](design/technical/technical-design-github-platform-support.md)
- [design/technical/technical-design-dashboard-remediation.md](design/technical/technical-design-dashboard-remediation.md)
- [design/functional/functional-design-remediation-recovery.md](design/functional/functional-design-remediation-recovery.md)
- [design/technical/technical-design-remediation-recovery.md](design/technical/technical-design-remediation-recovery.md)
- [design/functional/functional-design-pr-review-staged-pipeline.md](design/functional/functional-design-pr-review-staged-pipeline.md)
