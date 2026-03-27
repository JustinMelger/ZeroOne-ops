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

Not yet implemented:

- [x] issue selection wired into the runner
- [x] code context analysis
- [ ] LLM integration
- [ ] patch application
- [ ] git branch and commit automation
- [ ] GitLab merge request creation
- [ ] human approval workflow

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

- the runner selects one eligible issue
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

### Phase 4: LLM Analysis and Patch Proposal

Goal:

- classify issues as fixable or manual
- generate a proposed patch
- generate commit and merge request metadata

Done when:

- [ ] the LLM returns structured analysis and patch data
- [ ] invalid or unsafe responses are rejected
- [ ] patch proposals are constrained to allowed files

### Phase 5: Patch Application and Validation

Goal:

- apply generated patches locally
- run repository validation commands
- support one retry after validation failure

Done when:

- [ ] a generated patch can be applied safely
- [ ] validation output is captured and summarized
- [ ] failed validation can trigger one controlled retry

### Phase 6: Git Automation

Goal:

- verify repository preconditions
- create a work branch
- commit validated changes
- push the branch

Done when:

- [ ] the bot creates a predictable branch name
- [ ] unsafe repository states are rejected
- [ ] commit and push work from the configured repository root

### Phase 7: GitLab Merge Request Creation

Goal:

- create a merge request in GitLab
- include labels and issue metadata
- avoid duplicate merge requests

Done when:

- [ ] a validated branch can produce a GitLab merge request
- [ ] the merge request contains SonarQube context
- [ ] the local state records the merge request URL

### Phase 8: Human Approval Gate

Goal:

- pause after validation
- show change summary in the terminal
- require explicit human approval before publish

Done when:

- [ ] approval is required before commit and push
- [ ] rejection exits cleanly and updates state
- [ ] approval decisions are reflected in the run record

### Phase 9: Hardening

Goal:

- improve test coverage
- add coverage thresholds
- improve logging and failure classification
- tighten duplicate-processing safeguards

Done when:

- [ ] the main execution path is covered by tests
- [ ] CI enforces an agreed minimum coverage threshold
- [ ] failures are diagnosable from logs and state

## Recommended Implementation Order

- [x] Wire issue selection into the runner.
- [x] Improve the context builder around issue file and line.
- [ ] Implement git precondition checks and branch creation.
- [ ] Implement the GitLab client for merge request creation.
- [ ] Implement LLM analysis and patch generation.
- [ ] Implement patch apply and validation retry flow.
- [ ] Add the human approval gate.
- [ ] Harden coverage, logging, and failure handling.

## Deferred Beyond V1

- multi-issue processing per run
- automatic merge request approval or merge
- distributed or shared state storage
- support for GitHub in addition to GitLab
- advanced issue prioritization
- autonomous retry loops beyond one retry

## Working Rule

For v1, prefer shipping thin vertical slices over building all abstractions first.

Each phase should end with:

- working code,
- tests,
- passing quality checks,
- updated docs if behavior changes.
