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
- shared remediation execution, validation setup/check commands, provider-local
  change-request publishing, and bounded branch naming
- opt-in baseline-aware validation feedback: preserved baseline failures,
  one-file correction feedback, compact work-item evidence, and provider-native
  change-request validation summaries
- shared promotion capacity for issue-mode repositories, with a configurable
  active-work limit and aggregate capacity backlog visibility
- GitHub live validation from Ruff finding to remediation pull request, review
  projection, merge, and terminal work-item closure
- GitLab/GitHub closed-unmerged convergence: preserve traceability, block
  automatic retries, and require a later explicit operator recovery action
- MLflow tracing support, Ruff pre-commit checks, and current CI workflows
- copyable GitHub Actions and GitLab CI control-plane installation templates

## Current Focus

### Phase 7: Recovery Rollout

- [ ] implement and live-validate fresh-attempt branch identity on GitHub and
  GitLab
- design: [functional recovery contract](docs/design/functional/functional-design-remediation-recovery.md)
  and [technical implementation plan](docs/design/technical/technical-design-remediation-recovery.md)

### Phase 8: GitLab Issue-Mode Rollout

- [ ] live-validate the GitLab operational summary alongside issue-mode policy,
  remediation, recovery, lifecycle, dismissal suppression, blocked work, and
  stale-claim recovery in two repositories
- [ ] after each repository cutover, label and close its legacy dashboard while
  preserving it as readable history without competing authority
- design: [functional control-plane design](docs/design/functional/functional-design-gitlab-issue-control-plane.md)
  and [technical implementation plan](docs/design/technical/technical-design-gitlab-issue-control-plane.md#phase-8e-operational-summary-implementation-plan)

### Promotion Capacity Validation

- [ ] live-validate a small capacity in one GitHub and one GitLab issue-mode
  repository: confirm the queue stays bounded, a completed item frees a slot,
  and capacity deferrals appear only as aggregate backlog counts

### Phase 9: Validation Feedback Loop

- [ ] live-validate the opt-in loop in one GitHub and one GitLab issue-mode
  repository: clean validation, preserved baseline, corrected edited-file
  regression, and unscoped-regression blocking
- design: [functional validation feedback contract](docs/design/functional/functional-design-remediation-validation-feedback.md)
  and [technical implementation plan](docs/design/technical/technical-design-remediation-validation-feedback.md)

### Review Rollout

- [ ] live-validate same-SHA review-projection repair after a recoverable
  projection warning

### Runner Composition Cleanup

- [x] extract shared run context, lazy provider builders, derived operational
  summary composition, and GitLab combined control-plane sequencing while
  retaining current public runner entrypoints
- [ ] extract GitHub/GitLab finding-sync orchestration into focused workflow
  composition, retaining explicit legacy GitLab dashboard routing
- [ ] extract remediation, recovery, and work-item lifecycle orchestration into
  focused workflow composition without changing provider-local behavior
- [ ] extract policy orchestration and review the remaining `runner.py` entry
  points; retain only stable public routing and shared CLI-facing summaries

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
