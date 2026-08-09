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
- GitHub hybrid control plane: policy issue, authoritative work-item issues,
  lifecycle reconciliation, and a derived operational summary
- shared remediation execution, validation setup/check commands, provider-local
  change-request publishing, and bounded branch naming
- GitHub live validation from Ruff finding to remediation pull request, review
  projection, merge, and terminal work-item closure
- GitLab/GitHub closed-unmerged convergence: preserve traceability, block
  automatic retries, and require a later explicit operator recovery action
- MLflow tracing support, Ruff pre-commit checks, and current CI workflows

## Current Focus

### Phase 7: Remediation Recovery Design

- [x] lock the shared recovery contract: operator `requeue` or `dismiss`, with
  backend-selected publication retry or fresh attempt
- [x] lock terminal behavior: closed change requests stay blocked; dismissed
  findings remain suppressed; no-change local analysis completes the item
- [x] 7a: add shared recovery models, decisions, state migration, and tests
- [x] 7b: add verified publication-retry planning and provider adapters
- [x] 7c: add authorized GitLab dashboard-note and GitHub work-item commands
- [ ] 7d: add fresh-attempt branch identity and live validation on both providers
- design: [functional recovery contract](docs/design/functional/functional-design-remediation-recovery.md)
  and [technical implementation plan](docs/design/technical/technical-design-remediation-recovery.md)

### Phase 8: GitLab Issue Control Plane

- [x] 8a.1: extract neutral linked-change-request reconciliation and add
  dedicated GitLab issue-mode transport without changing dashboard behavior
- [x] 8a.2: add GitLab work-item parsing, rendering, lookup, upsert, and
  malformed-record handling
- [x] 8b: implement one GitLab policy issue with Maintainer/Owner-authorized
  note replay and shared policy loading
- [x] 8c.1: publish policy-promoted findings as authoritative GitLab work-item
  issues with stable identity lookup and stale-inventory reconciliation
- [x] 8c.2a: select and claim one eligible GitLab work-item issue using the
  shared execution-target contract
- [x] 8c.2b: execute claimed GitLab work items and project merge-request links
- [x] 8c.2c: project review outcomes onto the uniquely linked GitLab work item
- [x] 8d.1: add GitLab issue-mode lifecycle with stale-claim recovery,
  merge-request reconciliation, and terminal issue closure
- [x] 8d.2: add event-scoped GitLab work-item recovery
- [x] 8d.3: add the scheduled/manual issue-mode control-plane job: policy,
  paginated labelled work-item recovery notes, then remediation; start at a
  30-minute schedule
- [ ] 8d.4: label and close the legacy dashboard after cutover, preserving it as
  readable history without competing authority
- [x] 8e.1: extract the provider-neutral operational-summary view, bounded
  builder, renderer, parser, and persisted latest-finding-sync observation from
  the GitHub implementation; retain provider-local terminology so GitHub
  output does not change
- [x] 8e.2: adapt the existing GitHub summary to the shared core without
  changing its title, lookup, rendering, or best-effort publication behavior
- [x] 8e.3: add GitLab summary issue transport and a derived-summary service
  with stable title-and-label lookup, bounded rendering, and parser/renderer/
  store coverage
- [x] 8e.4: publish the GitLab derived summary best-effort after successful
  finding sync, control-plane transitions, and lifecycle reconciliation in
  `gitlab.control_plane_mode=issues` only
- [ ] 8e.5: update GitLab installation guidance and live-validate the summary
  alongside issue-mode policy, remediation, recovery, and lifecycle behavior
- [ ] 8e.6: live-validate policy, remediation, recovery, merge-request
  lifecycle, dismissal suppression, blocked items, and stale claims in two
  GitLab repositories
- [ ] 8f: after successful rollout, make dashboard mode maintenance-only for
  two minor releases, then remove it in a planned breaking release
- design: [functional control-plane design](docs/design/functional/functional-design-gitlab-issue-control-plane.md)
  and [technical implementation plan](docs/design/technical/technical-design-gitlab-issue-control-plane.md#phase-8e-operational-summary-implementation-plan)

### Control-Plane Installation UX

- [x] design one operator-facing control-plane installation per provider so
  GitHub Actions and GitLab CI present the same conceptual jobs: finding sync,
  remediation, lifecycle reconciliation, and optional recovery-command handling
- [x] ship one copyable GitHub workflow template and one GitLab CI template
  with the correct triggers, schedules, concurrency, permissions, variables,
  and required versus optional jobs already composed
- [x] update the README and runbook to describe this as one ZeroOne Ops
  control-plane installation, not a collection of independently wired commands

### Phase 9: Validation Feedback Loop

- capture a baseline for configured validation commands before applying a
  remediation patch
- compare post-edit validation against that baseline so unrelated existing
  failures are not attributed to the patch
- feed bounded, edited-file-relevant validation diagnostics into one retry
  generation pass
- keep the retry boundary to the original remediation target and one file;
  block with actionable diagnostics when broader repair is required

### Promotion Capacity

- [x] lock the shared v1 promotion-capacity design for GitLab and GitHub:
  `remediation.max_active_work_items` defaults to `10`; open `approved` and
  `in_progress` work items consume capacity, while blocked, dismissed, and
  terminal items remain visible without consuming a slot; eligible findings
  are ordered by severity with stable identity tie-breaking;
  deferred findings remain backlog-only with a visible
  `promotion_capacity_exhausted` reason
- [ ] implement the shared promotion budget while retaining full finding
  inventory sync and stale reconciliation for every normalized source
- [ ] surface promoted, deferred, and capacity-deferred counts in provider
  operator views

### Rollout And Feedback

- continue live validation of review quality, remediation outcomes, and policy
  ergonomics on both providers
- complete live validation of same-SHA review-projection repair
- prefer narrow fixes driven by observed runs over broad workflow expansion

### Maintainer Cleanup

- keep the public README and GitHub/GitLab examples aligned with the shipped
  neutral commands and provider-specific control planes
- reduce remaining runner composition duplication through a small workflow
  context/factory only when it improves clarity without changing behavior
- move remediation validation setup/check commands into a remediation-owned
  configuration block after sufficient rollout feedback confirms the current
  contract

## Parked For Later

- external API/database-backed control plane
- additional structured finding adapters and a later shared cross-source
  reconciliation/deduplication stage
- richer developer feedback consumption for review notes and broader review
  evaluator growth
- multi-file remediation and automated test-repair workflows
- broader dashboard/history presentation improvements after operator usage
  establishes the need

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
