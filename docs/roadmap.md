# AI Sonar Bot Roadmap

## Purpose

This roadmap translates the functional and technical design into an implementation sequence for v1.

It is intentionally short and execution-focused. The goal is to make the next steps obvious and keep scope controlled while the bot is being built.

## Current Status

Completed:

- [x] functional design
- [x] technical design
- [x] Python project scaffold with `uv`
- [x] local quality tooling with `ruff`, `mypy`, `pytest`, and `pytest-cov`
- [x] architecture boundary checks with `import-linter`
- [x] GitHub Actions quality workflow
- [x] local `just` commands
- [x] SonarQube client implementation
- [x] automatic `.env` loading
- [x] service-level refactor for issue intake and analysis orchestration
- [x] runner refactor into execution and run-state services
- [x] issue selection wired into the runner
- [x] code context analysis
- [x] LLM integration
- [x] patch application
- [x] git branch and commit automation
- [x] GitLab merge request creation
- [x] CI execution mode

Still open:

- [x] richer failure logging in state and logs

## V1 Delivery Phases

### Phase 1: SonarQube Intake

Goal:

- fetch open SonarQube issues for the configured project
- normalize issues into internal models
- verify local file mapping

Status:

- [x] fetch open SonarQube issues for the configured project
- [x] normalize issues into internal models
- [x] verify local file mapping

Done when:

- the bot can retrieve open issues from SonarQube
- issue payloads are normalized consistently
- dry-run can report real issue counts

### Phase 2: Issue Selection

Goal:

- filter unsupported issues
- skip issues already handled
- select one actionable issue per run
- persist selection state

Status:

- [x] filter unsupported issues
- [x] skip issues already handled
- [x] select one actionable issue per run
- [x] persist selection state

Done when:

- `IssueIntakeService` selects one eligible issue
- the selected issue is stored in state
- dry-run shows the selected issue key, file, rule, and severity

### Phase 3: Local Code Analysis

Goal:

- build source context around the issue location
- identify relevant file content for analysis
- prepare structured input for the LLM

Done when:

- [x] the context builder returns focused code context
- [x] missing files or missing lines are handled cleanly
- [x] the analysis input is stable enough for prompt construction
- [x] analysis orchestration is isolated in a dedicated service

### Phase 4: LLM Analysis and Patch Proposal

Goal:

- classify issues as fixable or manual
- generate a proposed patch
- generate commit and merge request metadata

Done when:

- [x] the LLM returns structured analysis data
- [x] the LLM returns structured patch data
- [x] invalid or unsafe responses are rejected
- [x] patch proposals are constrained to allowed files

### Phase 5: Patch Application and Validation

Goal:

- apply generated patches locally
- run repository validation commands
- support one retry after validation failure

Done when:

- [x] a generated patch can be applied safely
- [x] validation output is captured and summarized
- [x] failed validation can trigger one controlled retry

### Phase 6: Git Automation

Goal:

- verify repository preconditions
- create a work branch
- commit validated changes
- push the branch

Done when:

- [x] the bot creates a predictable branch name
- [x] unsafe repository states are rejected
- [x] commit and push work from the configured repository root

### Phase 7: GitLab Merge Request Creation

Goal:

- create a merge request in GitLab
- include labels and issue metadata
- avoid duplicate merge requests

Done when:

- [x] a validated branch can produce a GitLab merge request
- [x] the merge request contains SonarQube context
- [x] the local state records the merge request URL
- [x] duplicate open merge requests are reused instead of recreated

### Phase 8: Human Approval Gate

Goal:

- support non-interactive CI execution
- use GitLab merge request review as the approval gate in pipelines
- keep optional local interactive approval for developer-triggered runs

Done when:

- [x] CI mode bypasses terminal prompts and creates merge requests automatically
- [x] local mode can still request interactive approval when enabled
- [x] approval behavior is reflected in config and run state

### Phase 9: Hardening

Goal:

- improve test coverage
- add coverage thresholds
- improve logging and failure classification
- tighten duplicate-processing safeguards

Done when:

- [ ] the main execution path is covered by tests
- [x] CI enforces an agreed minimum coverage threshold
- [x] failures are diagnosable from logs and state

## Recommended Implementation Order

- [x] Wire issue selection into the runner.
- [x] Improve the context builder around issue file and line.
- [x] Extract issue intake and analysis orchestration into dedicated services.
- [x] Implement git precondition checks and branch creation.
- [x] Implement the GitLab client for merge request creation.
- [x] Implement LLM analysis and patch generation.
- [x] Implement patch apply and validation retry flow.
- [x] Add optional local approval flow.
- [x] Harden duplicate-MR messaging and reuse behavior.
- [x] Harden logging and failure handling.

## Deferred Beyond V1

- multi-issue processing per run
- automatic merge request approval or merge
- distributed or shared state storage
- support for GitHub in addition to GitLab
- advanced issue prioritization
- autonomous retry loops beyond one retry

## Post-V1: GitHub Support

After the GitLab-first v1 is complete, GitHub support should be added as a
focused follow-up rather than folded into the v1 scope.

Required changes:

- add a GitHub provider client alongside the existing GitLab client
- introduce an SCM provider switch in configuration
- extract a provider-neutral publish interface for merge request or pull request creation
- rename GitLab-specific publish concepts in shared models and services to neutral change-request terms where needed
- support GitHub repository identification and token configuration
- implement duplicate pull request detection for GitHub
- map labels, reviewers, and assignees to GitHub APIs
- update state fields if they are too GitLab-specific, for example `mr_url`
- add GitHub integration tests and CI coverage for the publish layer

Done when:

- a validated branch can create a GitHub pull request through a provider-neutral publish flow
- the state model can persist either GitLab merge request URLs or GitHub pull request URLs cleanly
- shared workflow code does not depend on GitLab-only terminology outside the GitLab provider layer

## Working Rule

For v1, prefer shipping thin vertical slices over building all abstractions first.

Each phase should end with:

- working code,
- tests,
- passing quality checks,
- updated docs if behavior changes.
