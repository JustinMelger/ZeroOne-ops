## Operator Runbook

This runbook describes how to operate AI Sonar Bot in GitLab CI for the
current SonarQube-first v1 scope.

## Purpose

Use this document when you need to:

- configure the bot in a target repository
- understand what a normal run should do
- diagnose skipped runs, failed runs, or merge request reuse
- know which credentials and permissions are required

## Supported V1 Scope

The current v1 automation scope is intentionally narrow:

- one SonarQube issue per run
- low-severity maintainability issues only
- low-risk single-file fixes only
- structured-edit generation with bot-rendered diffs
- GitLab merge request creation in `ci` mode

The bot currently excludes rename-style issues by design. Rename changes need
symbol-reference safety checks that are not part of v1 yet.

## Required CI Variables

Define these variables in the target GitLab project or group:

- `SONARQUBE_URL`
- `SONARQUBE_TOKEN`
- `SONARQUBE_PROJECT_KEY`
- `GITLAB_URL`
- `GITLAB_TOKEN`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

Optional variables:

- `GITLAB_PROJECT_ID`
  - not required in GitLab CI when `CI_PROJECT_ID` is present
- `AI_SONAR_BOT_EXECUTION_MODE`
  - should be `ci` for pipeline usage
- `AI_SONAR_BOT_OPENAI_SOLUTION_OUTPUT_PATH`
  - only needed if you want a non-default local artifact path
- `AI_SONAR_BOT_WRITE_SOLUTION_ARTIFACTS_IN_CI`
  - defaults to `false`
  - set to `true` only for debugging

## Required Token Permissions

`SONARQUBE_TOKEN` must be able to read open issues for the configured project.

`GITLAB_TOKEN` must be able to:

- push branches to the target repository
- create merge requests
- read open merge requests for duplicate detection

In practice, this means the token should have:

- API access for merge request operations
- repository write access for branch pushes

`OPENAI_API_KEY` must be valid for the configured `OPENAI_MODEL`.

## Expected Pipeline Behavior

In normal `ci` mode, one run should do the following:

1. fetch open SonarQube issues
2. filter to locally existing files
3. skip issues already represented by an open bot merge request or active state
4. select the next eligible issue
5. build focused context for that issue
6. run OpenAI analysis
7. request a structured edit
8. render the diff locally in the bot
9. apply the patch
10. run validation commands
11. commit and push a branch
12. create or reuse a GitLab merge request

If no eligible issue remains, the run should exit cleanly with `no_issue`.

## Expected Merge Request Shape

The merge request should contain:

- one issue per branch
- labels from `.ai-sonar-bot.json`
- a deterministic description template with:
  - issue key
  - rule
  - severity
  - type
  - file
  - line
  - issue message
  - validation summary
  - note that the diff was bot-rendered from a structured edit proposal

## Recommended GitLab CI Setup

Use the example pipeline from [.gitlab-ci.example.yml](/Users/justinmelger/Desktop/github/ai-sonar-bot/.gitlab-ci.example.yml).

Recommended settings:

- run only on the default branch
- trigger from a schedule or explicit manual run
- use `resource_group` so only one bot job runs at a time
- use `GIT_DEPTH=0`
- set a fixed git author/committer identity
- rewrite `origin` to use `GITLAB_TOKEN` for authenticated pushes

## Common Outcomes

### No Issue Selected

This is expected when:

- SonarQube credentials are missing
- no open issues match the configured severity and type filters
- remaining issues point to files not present in the repository
- remaining issues are already represented by open bot merge requests
- remaining issues are excluded by v1 safeguards such as rename-style issue skipping

### Merge Request Reused

This is expected when:

- the predicted bot branch already has an open merge request

The bot should skip that issue and move to the next eligible one. If no other
issue qualifies, the run exits cleanly.

### Run Failed

Look at:

- pipeline logs
- the final run summary
- `.ai-sonar-bot-state.json` if local state persistence is enabled in the repo

The failure record should tell you:

- stage
- message
- retry count
- failed validation command when relevant
- exit code when relevant

## Common Failure Modes

### Missing Configuration

Symptoms:

- run stops before issue selection or publish
- error mentions missing environment variables

Checks:

- confirm the CI variables exist
- confirm protected variables are available to the branch/pipeline context

### No OpenAI Output

Symptoms:

- analysis step reports no LLM backend configured

Checks:

- confirm `OPENAI_API_KEY` is present
- confirm `OPENAI_MODEL` is present
- confirm the repository is not accidentally using local fixture-only settings

### Patch Apply Failure

Symptoms:

- run fails during patch application

Checks:

- inspect the issue type
- confirm it is not a rename-style issue or another unsupported pattern
- confirm the repository content still matches the expected source around the target line

### Validation Failure

Symptoms:

- patch applies but validation fails
- run may retry once, then stop

Checks:

- inspect the failed command in the logs
- inspect whether the selected issue was actually low-risk enough for the current eligibility policy
- confirm the validation commands in `.ai-sonar-bot.json` are correct for the target repo

### Branch Push Failure

Symptoms:

- commit succeeds but publish fails

Checks:

- confirm `GITLAB_TOKEN` can push branches
- confirm the CI job rewrites `origin` to an authenticated URL
- confirm branch protections do not block the bot branch pattern

### Merge Request Creation Failure

Symptoms:

- branch is pushed but no merge request is created

Checks:

- confirm `GITLAB_TOKEN` has API access
- confirm `GITLAB_URL` and project identification are correct
- confirm the repository allows merge request creation from the bot token

## Recovery Steps

When a run fails:

1. identify the failure stage from the run summary or logs
2. correct the root cause
3. rerun the pipeline manually or wait for the next scheduled run

When an issue already has an open merge request:

1. review or close that merge request
2. rerun the bot only after deciding whether the issue should remain in scope

When a merge request should no longer be managed by the bot:

1. close the merge request
2. resolve or reclassify the SonarQube issue
3. rerun only if the issue should still be considered eligible

## Debugging Guidance

Use CI solution artifacts only when you need extra debugging detail. They are
disabled by default in `ci` mode to reduce artifact churn.

If you need them temporarily:

- set `AI_SONAR_BOT_WRITE_SOLUTION_ARTIFACTS_IN_CI=true`
- rerun the pipeline
- remove the override once debugging is done

## Pre-Release Checklist

Before calling the target repository setup stable, confirm:

- the pipeline can fetch SonarQube issues
- the bot creates exactly one branch and one merge request per issue
- duplicate issues are skipped on rerun
- validation commands match the repository
- the GitLab token can both push and create merge requests
- operators know where to inspect failures and how to rerun safely
