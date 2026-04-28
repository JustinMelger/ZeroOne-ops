## ZeroOne Ops Operator Runbook

This runbook describes how to operate the current ZeroOne Ops workflows in
GitLab CI.

Naming note:

- product brand: `ZeroOne Ops`
- technical release and image slug: `zeroone-ops`
- operator-facing commands, config examples, and container paths now use the `zeroone-ops` names

Legacy compatibility aliases still work under the hood, but operator-facing setup now uses the `ZeroOne Ops` names throughout.

## Purpose

Use this document when you need to:

- configure the bot in a target repository
- understand what a normal run should do
- diagnose skipped runs, failed runs, or merge request reuse
- know which credentials and permissions are required
- run the merge request review workflow and validate its output

## Supported V1 Scope

The current v1 automation scope is intentionally narrow:

- one SonarQube issue per run
- low-severity maintainability issues only
- low-risk single-file fixes only
- structured-edit generation with bot-rendered diffs
- structured edits must touch exactly one file
- GitLab merge request creation in `ci` mode
- severity-based intake control seeded from `supported_severities`, with
  built-in safety guards for issue classes the bot should not automate

Current config shape for rollout:

- shared runtime settings remain top-level
- review behavior lives under `review`
- remediation policy lives under `remediation`
- Sonar-specific local fixture behavior lives under `sonarqube`

In practice, the main remediation rollout keys now are:

- `remediation.supported_severities`
- `remediation.max_retry_count`
- `remediation.analysis`
- `sonarqube.mock_issues_path`

Authority note:

- `remediation.supported_severities` is the bootstrap/default seed for a new
  dashboard severity policy
- once the dashboard has canonical policy state, remediation pickup follows
  the dashboard policy instead of treating config severity as the active
  operator control plane
- operators should change ongoing severity policy through strict
  `/zeroone policy ...` dashboard comments

Legacy flat keys still work during migration, but new repository rollouts
should use the nested shape.

The bot currently excludes rename-style issues by design. Rename changes need
symbol-reference safety checks that are not part of v1 yet.

If the LLM proposes a structured edit that touches more than one file, the run
fails at analysis instead of trying to widen scope automatically.

The repository also contains a GitLab-first pull request review v1 workflow:

- one merge request per run
- one deterministic summary note per reviewed revision
- dedup by merge request IID and head SHA
- no inline comments in v1
- no code modification in the review workflow
- draft merge requests skipped by default

The dashboard workflow also includes scheduled reconciliation:

- one `mr_opened` dashboard item per run
- GitLab merge request state lookup using stored MR traceability
- deterministic transitions to `done`, `open`, or `failed`
- CI-only live execution, with local inspection limited to `--dry-run`

The dashboard also renders an operator policy surface:

- current severity policy is shown as read-only descriptive state
- excluded issue classes and grouped issue inventory are shown for visibility
- policy actions should be issued as strict dashboard issue comments beginning
  with `/zeroone policy`
- direct dashboard markdown edits and raw checkbox toggles are display-only and
  are not the authoritative mutation path
- when an older recognized dashboard body is loaded, ZeroOne Ops rewrites it
  into the current schema before continuing normal dashboard-backed workflows

## Required CI Variables

Define these variables in the target GitLab project or group according to the
workflow you want to run:

- `zeroone_ops_dashboard`
  - `SONARQUBE_URL`
  - `SONARQUBE_TOKEN`
  - `SONARQUBE_PROJECT_KEY`
  - `GITLAB_URL`
  - `GITLAB_TOKEN`
- `zeroone_ops_dashboard_remediate`
  - `GITLAB_URL`
  - `GITLAB_TOKEN`
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`
- `zeroone_ops_dashboard_reconcile`
  - `GITLAB_URL`
  - `GITLAB_TOKEN`
- `zeroone_ops_review`
  - `GITLAB_URL`
  - `GITLAB_TOKEN`
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`

Optional variables:

- `GITLAB_PROJECT_ID`
  - not required in GitLab CI when `CI_PROJECT_ID` is present
- `ZEROONE_OPS_EXECUTION_MODE`
  - should be `ci` for pipeline usage
- `ZEROONE_OPS_OPENAI_SOLUTION_OUTPUT_PATH`
  - only needed if you want a non-default local artifact path
- `ZEROONE_OPS_WRITE_SOLUTION_ARTIFACTS_IN_CI`
  - defaults to `false`
  - set to `true` only for debugging

## Required Token Permissions

`SONARQUBE_TOKEN` must be able to read open issues for the configured project.

`GITLAB_TOKEN` must be able to:

- push branches to the target repository
- create merge requests
- read open merge requests for duplicate detection
- read and update the dashboard issue used by dashboard-backed workflows

In practice, this means the token should have:

- API access for merge request operations
- repository write access for branch pushes

Store CI secrets such as `GITLAB_TOKEN`, `SONARQUBE_TOKEN`, and
`OPENAI_API_KEY` as masked and protected variables. When CI rewrites the git
remote for authenticated pushes, avoid enabling shell tracing around that step.

`OPENAI_API_KEY` must be valid for the configured `OPENAI_MODEL`.

For GitHub-hosted release and dependency workflows:

- `RELEASE_PLEASE_TOKEN` must be available to the release workflow when using
  release-please automation
- `RENOVATE_TOKEN` must be available to the Renovate workflow
- prefer repository or organization secrets rather than hard-coded workflow
  values

For pull request review, `GITLAB_TOKEN` must also be able to:

- list open merge requests
- read merge request changes
- create merge request notes

## Release Checklist

Use this lightweight checklist before cutting a stable release tag.

1. confirm the working tree is ready and the intended version/tag is clear
2. confirm CI quality checks are green:
   - `uv run ruff check .`
   - `just architecture`
   - `uv run mypy src`
   - `uv run bandit -q -r src`
   - `uv run pytest`
3. confirm required release and runtime secrets are configured:
   - `RELEASE_PLEASE_TOKEN` for GitHub release automation if used
   - `OPENAI_API_KEY` where live review or remediation flows will run
   - `GITLAB_TOKEN` for GitLab-backed live workflows
4. when using release-please, prefer squash merge with a conventional PR title
   so the commit that lands on `main` stays parseable for release automation
5. if the change is significant, publish and test a prerelease tag first, for
   example `zeroone-ops-vX.Y.Z-rc.N`
6. confirm the publish-image workflow smoke test passes for the container:
   - `--help`
   - `review --help`
   - `dashboard --help`
7. confirm README, runbook, and example CI docs still match the current release
   and image naming
8. record any known rollout caveats before cutting the stable tag

A stable release is ready when the checklist is complete and there are no known
blocking rollout issues.

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

## Expected Review Workflow Behavior

In normal `ci` mode, one review run should do the following:

1. if `CI_MERGE_REQUEST_IID` is present, fetch only that merge request
2. otherwise, fetch open GitLab merge requests
3. skip merge request revisions already reviewed for the current head SHA
4. select the triggering merge request or the next reviewable merge request
4. load changed-file diff data and bounded local source context
5. run OpenAI review analysis
6. classify the result as:
   - `findings_present`
   - `no_findings`
   - `manual_review_only`
7. publish one deterministic summary note unless the run is a dry-run
8. persist the reviewed MR IID and head SHA in state

If no reviewable merge request remains, the run should exit cleanly with `no_issue`.

## Expected Merge Request Shape

The merge request should contain:

- one issue per branch
- labels from `examples/.zeroone-ops.json` or the repository-specific runtime
  config derived from it
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

Use the example pipeline from
[examples/.gitlab-ci.example.yml](../examples/.gitlab-ci.example.yml).

Current job roles:

- `zeroone_ops_dashboard`
  - discovery-only dashboard sync for eligible Sonar findings
- `zeroone_ops_dashboard_remediate`
  - dashboard-backed remediation
- `zeroone_ops_dashboard_reconcile`
  - scheduled dashboard reconciliation for `mr_opened` items after merge
    request state changes
- `zeroone_ops_review`
  - merge request review note publication with no code changes

Recommended settings:

- run only on the default branch
- trigger from a schedule or explicit manual run
- keep dashboard sync as a separate job from active remediation
- keep dashboard-backed remediation as a separate job from dashboard sync, but
  run it after dashboard sync in the same pipeline with `needs:` or explicit
  stage ordering
- keep dashboard reconciliation as a separate job from active remediation so it
  only owns post-merge-request lifecycle convergence
- use `resource_group` per workflow so overlapping runs of the same workflow do
  not collide
- override the job image `entrypoint` to `[""]`
- use `GIT_DEPTH=0`
- set a fixed git author/committer identity
- rewrite `origin` to use `GITLAB_TOKEN` for authenticated pushes

For review-only jobs, branch push credentials are not required because the
workflow only reads merge requests and writes merge request notes.

For a lower-cost review setup:

- keep the review job manual on merge request pipelines
- rely on `CI_MERGE_REQUEST_IID` so the bot reviews only the current merge request
- set `review.max_changed_files` conservatively, for example `5`
- set `review.ignored_paths` for generated or otherwise low-value areas
- keep `review.max_findings_per_review` low so only the highest-signal findings are published
- keep `review.skip_draft_merge_requests` enabled
- set `review.publish_no_findings_note` to `false` if you want less MR noise and lower cost

Recommended first rollout order:

1. manually run `zeroone_ops_dashboard` once to confirm dashboard discovery is healthy
2. inspect one supported dashboard item locally with `zeroone-ops dashboard remediate --dry-run`
3. manually run one live CI pipeline where `zeroone_ops_dashboard_remediate`
   follows `zeroone_ops_dashboard`
4. manually run `zeroone_ops_dashboard_reconcile` once after a remediation MR
   is merged or closed
5. manually run `zeroone_ops_review` on one small merge request pipeline
6. enable schedules only after all workflows behave as expected

Dashboard rollout model:

- keep Sonar dashboard sync as a separate discovery producer for Sonar-derived dashboard items
- treat `dashboard sync` then `dashboard remediate` as the normal ordered CI
  flow for active remediation work
- keep `dashboard reconcile` as a separate later lifecycle job rather than
  chaining it directly after remediation
- keep live `dashboard remediate` CI-only in the first version; local use should stay `--dry-run`
- keep live `dashboard reconcile` CI-only in the first version; local use should stay `--dry-run`
- let Sonar dashboard sync clean up only stale untouched `open` Sonar items; once remediation has touched an item, preserve the dashboard lifecycle history

## Expected Reconciliation Workflow Behavior

In normal `ci` mode, one reconciliation run should do the following:

1. load the dashboard
2. select one `mr_opened` item with stored MR URL, branch name, and commit SHA
3. fetch the current merge request state from GitLab
4. decide one lifecycle outcome:
   - `done` when the MR was merged
   - `open` when the MR was closed without merge and the work still remains
   - `done` when the MR was closed without merge and the dashboard shows the
     Sonar issue is no longer active
   - `failed` when MR metadata is missing, inaccessible, or no longer matches
     stored traceability
5. update the dashboard item while preserving remediation metadata
6. persist the reconciliation outcome in local state

If no reconciliation-ready item remains, the run should exit cleanly with
`no_issue`.

## Common Outcomes

### No Issue Selected

This is expected when:

- SonarQube credentials are missing
- no open issues match the configured severity and type filters
- remaining issues point to files not present in the repository
- remaining issues are already represented by open bot merge requests
- remaining issues are excluded by v1 safeguards such as rename-style issue skipping

### No Merge Request Selected

This is expected when:

- GitLab credentials are missing
- no open merge requests exist
- open merge requests were already reviewed for the current head SHA

### Merge Request Reused

This is expected when:

- the predicted bot branch already has an open merge request

The bot should skip that issue and move to the next eligible one. If no other
issue qualifies, the run exits cleanly.

### Review Note Published

This is expected when:

- one merge request was selected
- review context was built successfully
- the LLM returned a valid structured review result
- GitLab note publication succeeded

The note should be a single summary comment, not multiple inline comments.

If dashboard mirroring is enabled later, the review note is still the primary
output surface. A dashboard update failure after note publication should not
turn the whole review run into a failed review.

### Run Failed

Look at:

- pipeline logs
- the final run summary
- `.zeroone-ops-state.json` if local state persistence is enabled in the repo

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
- confirm the validation commands in the repository-specific `.zeroone-ops.json`
  are correct for the target repo

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

### Review Context Failure

Symptoms:

- the review run fails before note publication
- the message mentions missing changed files or the merge request exceeding limits

Checks:

- confirm the merge request changes are present in the checked-out repository
- confirm the changed-file count is within the configured v1 review limit
- confirm review-supported paths are configured correctly if path filtering is enabled

### Review Note Publication Failure

Symptoms:

- review analysis succeeds but no note is created

Checks:

- confirm `GITLAB_TOKEN` can create merge request notes
- confirm the target merge request still exists and is open
- confirm `GITLAB_PROJECT_ID` / `CI_PROJECT_ID` match the repository being reviewed

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

- set `ZEROONE_OPS_WRITE_SOLUTION_ARTIFACTS_IN_CI=true`
- rerun the pipeline
- remove the override once debugging is done

## Smoke Test Recipe

Use this recipe before you rely on the bot for unattended scheduled runs in a
new repository.

### Preconditions

Make sure the target repository has:

- a valid `.gitlab-ci.yml` based on
  [examples/.gitlab-ci.example.yml](../examples/.gitlab-ci.example.yml)
- the published bot image reference updated to the current technical slug, such
  as `ghcr.io/<owner>/zeroone-ops:latest`
- a repository-specific `.zeroone-ops.json`, often copied from either:
  - [examples/.zeroone-ops.minimal.json](../examples/.zeroone-ops.minimal.json)
  - [examples/.zeroone-ops.json](../examples/.zeroone-ops.json)
- required CI variables set
- at least one open SonarQube issue that is:
  - low severity in the maintainability model
  - in a file that exists in the repository
  - within the current v1 rule allowlist
  - expected to require only one-file structured edits

### JSON Config Quick Guide

The repository-level `.zeroone-ops.json` has a small required core.

Required JSON fields:

- `base_branch`
- `gitlab.target_branch`

Everything else in the JSON config is optional and falls back to application
defaults unless your repository needs custom behavior.

This means:

- use the minimal example when you only need a working starting point
- use the fuller example when you want to pin validation commands, review
  limits, labels, or other repo-specific behavior explicitly
- credentials such as GitLab, SonarQube, and OpenAI tokens are still provided
  through environment variables or CI variables, not through this JSON file

Minimal valid example:

```json
{
  "base_branch": "main",
  "gitlab": {
    "target_branch": "main"
  }
}
```

Fuller example:

- [examples/.zeroone-ops.json](../examples/.zeroone-ops.json)

### Recommended First Test

Start with one intentionally simple issue, ideally something equivalent to:

- `python:S1125`
- one local file
- one exact text replacement

Do not use a rename issue or a fix that obviously needs multiple files.

### Steps

1. confirm the target repository pipeline can pull the `zeroone-ops` bot image successfully
2. confirm the bot job has access to:
   - SonarQube
   - OpenAI
   - GitLab push and merge request APIs
3. trigger the bot job manually instead of waiting for a schedule
4. watch the pipeline logs for:
   - issue count fetched
   - selected issue key
   - structured edit generation
   - diff rendered by bot
   - validation success
   - branch push
   - merge request created or reused
5. open the created merge request
6. verify the merge request description contains:
   - issue key
   - rule
   - severity
   - file
   - issue message
   - validation summary
   - bot-rendered diff note
7. inspect the diff and confirm it stays within one file
8. verify the branch name maps to the issue key and file path as expected

### Expected Healthy Outcome

A successful smoke test should produce:

- one selected SonarQube issue
- one bot branch
- one merge request
- a diff limited to one file
- passing validation in the pipeline logs
- no duplicate merge request creation on an immediate rerun

### Recommended Follow-Up Check

After the first successful run:

1. rerun the pipeline once
2. confirm the existing issue is skipped because an open merge request already exists
3. confirm the bot either:
   - selects the next eligible issue, or
   - exits cleanly with `no_issue`

### Failure Signals That Should Block Rollout

Do not move to scheduled unattended runs yet if you see:

- rename-style issues being selected
- multi-file structured edits proposed
- validation failures on supposedly low-risk rules
- repeated attempts against the same open merge request
- merge requests whose diffs widen beyond the selected issue
- branch push or merge request creation auth instability

## Review Smoke Test Recipe

Use this recipe before enabling scheduled or manual GitLab MR review runs in a
repository.

### Preconditions

Make sure the target repository has:

- a valid `.gitlab-ci.yml` that can run `zeroone-ops review`
- required review variables set:
  - `GITLAB_URL`
  - `GITLAB_TOKEN`
  - `GITLAB_PROJECT_ID` or `CI_PROJECT_ID`
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`
- at least one open merge request with a small, reviewable diff

### Recommended First Review

Start with one merge request that:

- changes one or two source files
- has a small diff
- is not already reviewed by the bot
- is easy for a human to evaluate for note quality

### Steps

1. confirm the repository pipeline can pull the `zeroone-ops` bot image successfully
2. confirm the review job has access to:
   - GitLab merge request APIs
   - OpenAI
3. trigger the review job manually
4. watch the logs for:
   - open merge request count
   - selected merge request IID and head SHA
   - review context build success
   - review classification
   - note publication
5. open the target merge request
6. verify there is one deterministic AI review summary note
7. confirm the note is clearly one of:
   - findings present
   - no findings in this pass
8. rerun the review job immediately
9. confirm the unchanged MR revision is skipped cleanly

### Expected Healthy Outcome

A successful review smoke test should produce:

- one selected merge request
- one deterministic summary note
- a persisted reviewed revision keyed by MR IID and head SHA
- a clean skip on immediate rerun when the head SHA is unchanged

### Failure Signals That Should Block Rollout

Do not move to unattended review runs yet if you see:

- repeated notes on the same unchanged merge request revision
- review notes that are malformed or inconsistent in shape
- review runs failing to read merge request changes reliably
- comments being published when the run should have been a dry-run

## Dashboard Discovery Smoke Check

Use this quick check after the remediation workflow is already healthy.

For dashboard-backed remediation itself, keep the first rollout boundary simple:
use `zeroone-ops dashboard remediate --dry-run` for local inspection and use
live `zeroone-ops dashboard remediate` only from CI jobs.

### Preconditions

Make sure the target repository has:

- the `zeroone_ops_dashboard` job from the example pipeline
- the same SonarQube and GitLab CI variables used by remediation
- at least one eligible SonarQube finding that should appear in the dashboard

### Steps

1. trigger `zeroone_ops_dashboard` manually on the default branch
2. watch the logs for the eligible issue count and dashboard sync summary
3. open the dashboard issue in GitLab
4. confirm the synced Sonar item appears once in the expected section
5. rerun the dashboard job once and confirm the same item is updated instead of duplicated

### Expected Healthy Outcome

- one persistent dashboard issue exists or is reused
- eligible Sonar items appear in structured sections
- an immediate rerun updates existing dashboard items instead of duplicating them
- stale untouched `open` Sonar items disappear or move out of the open section when they no longer exist upstream
- Sonar-derived items already in remediation-owned states such as `in_progress` or `mr_opened` remain visible instead of being cleared by sync

## Dashboard Remediation Smoke Test Recipe

Use this recipe before enabling scheduled dashboard-backed remediation in a
repository.

### Preconditions

Make sure the target repository has:

- the `zeroone_ops_dashboard` discovery job already behaving as expected
- one supported Sonar-derived dashboard item in `open`
- required GitLab and OpenAI CI variables set:
  - `GITLAB_URL`
  - `GITLAB_TOKEN`
  - `GITLAB_PROJECT_ID` or `CI_PROJECT_ID`
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`

### Recommended First Candidate

Start with one dashboard item that:

- was produced by Sonar dashboard sync
- maps to the current narrow single-file code-smell remediation path
- points to a file that exists on the default branch
- is easy for a human to inspect afterward

### Steps

1. run `zeroone-ops dashboard remediate --dry-run` locally
2. confirm the output reports one selected dashboard item and no lifecycle mutation
3. trigger one live dashboard remediation CI job manually on the default branch
4. watch the logs for:
   - stale `in_progress` recovery, if applicable
   - selected dashboard item ID
   - transition to `in_progress`
   - remediation analysis and validation
   - merge request creation or reuse
   - transition to `mr_opened`
5. open the dashboard issue in GitLab
6. confirm the selected item:
   - moved out of `open`
   - appears in the merge-request section with branch, MR URL, and commit traceability
7. open the merge request
8. verify the merge request description and diff quality still match the documented remediation expectations:
   - one-file diff
   - issue traceability
   - validation summary
   - bot-rendered diff note
9. rerun the dashboard remediation job once immediately
10. confirm the same item is not selected again while the merge request is still open

### Expected Healthy Outcome

- one supported dashboard item is reopened first if it was stale `in_progress`
- one live run moves the item through `in_progress` and `mr_opened`
- the dashboard item keeps visible traceability fields for run, branch, commit, and merge request
- an immediate rerun skips the open merge request cleanly instead of creating duplicate work
- the resulting merge request remains traceable and easy for humans to review

### Failure Signals That Should Block Rollout

Do not move to scheduled dashboard remediation yet if you see:

- dashboard items being selected without first passing through `open`
- stale `in_progress` items that are never reopened
- dashboard remediation succeeding locally but leaving the dashboard lifecycle stale
- Sonar dashboard sync clearing items that are already `in_progress` or `mr_opened`
- merge requests with poor traceability or unexpectedly weak diff quality

## Pre-Release Checklist

Before calling the target repository setup stable, confirm:

- the pipeline can fetch SonarQube issues
- the bot creates exactly one branch and one merge request per issue
- duplicate issues are skipped on rerun
- validation commands match the repository
- the GitLab token can both push and create merge requests
- operators know where to inspect failures and how to rerun safely
- the smoke test and immediate rerun both behave as expected
- Sonar dashboard sync remains the discovery/update mechanism for Sonar-derived dashboard items and does not replace later merge-request reconciliation
