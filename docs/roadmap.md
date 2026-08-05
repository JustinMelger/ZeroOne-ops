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

- define one provider-neutral recovery model for blocked remediation work
- support explicit operator choices: dismiss, retry a recorded publication
  branch when safe, or start a fresh attempt
- keep closed change requests non-retryable until an operator makes that choice
- implement GitLab and GitHub recovery adapters only after the shared contract
  and operator UX are locked

### Phase 8: Validation Feedback Loop

- capture a baseline for configured validation commands before applying a
  remediation patch
- compare post-edit validation against that baseline so unrelated existing
  failures are not attributed to the patch
- feed bounded, edited-file-relevant validation diagnostics into one retry
  generation pass
- keep the retry boundary to the original remediation target and one file;
  block with actionable diagnostics when broader repair is required

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

- evolve GitLab from its all-in-one dashboard issue toward the GitHub-style
  hybrid model: authoritative work items, separate policy, and optional derived
  overview
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
- [design/functional/functional-design-pr-review-staged-pipeline.md](design/functional/functional-design-pr-review-staged-pipeline.md)
