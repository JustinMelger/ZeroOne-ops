# AI Sonar Bot

AI Sonar Bot is a Python CLI that fetches open SonarQube issues, analyzes one issue, prepares a fix, validates the change, and creates a GitLab merge request for human review.
The same image and CLI also contain a GitLab merge request review workflow.

## Status

This repository currently contains:

- functional and technical design documents,
- an operator runbook,
- a Python project scaffold,
- configuration and state models,
- a working GitLab-first execution pipeline.

Implemented today:

- SonarQube issue intake and selection
- focused code context building
- fixture-backed and OpenAI-backed analysis
- patch generation, application, validation, and single retry
- local branch creation and commit flow
- CI-mode branch push and GitLab merge request creation or reuse
- a conservative built-in Sonar rule allowlist unless `supported_rules` is explicitly overridden
- explicit v1 enforcement that structured edits may touch exactly one file

## Tooling

- `uv` for environment and dependency management
- `ruff` for linting and formatting
- `mypy` for static type checking
- `pytest` and `pytest-cov` for tests and coverage
- `import-linter` for architecture boundary checks

## Getting Started

```bash
uv sync
uv run ai-sonar-bot dashboard sonar --dry-run
uv run ai-sonar-bot dashboard remediate --dry-run
uv run ai-sonar-bot review --dry-run
```

## Dry-Run With Fixture Data

When the repository is not connected to a real SonarQube project yet, dry-run can use a local fixture file instead.

The scaffold includes [fixtures/sonar/issues.json](fixtures/sonar/issues.json), and `.ai-sonar-bot.json` points to it by default through `mock_sonar_issues_path`.
The default Sonar fixture now targets [samples/auto_fixable_example.py](samples/auto_fixable_example.py), which is intentionally simple so the real OpenAI dry-run has an auto-fixable test case.

For analysis-only dry-runs, the scaffold also includes [fixtures/llm/analysis.json](fixtures/llm/analysis.json) through `mock_llm_analysis_path`.

For structured-edit dry-runs, the scaffold also includes [fixtures/llm/edit.json](fixtures/llm/edit.json) through `mock_llm_edit_path`.

This fixture mode is only used during dry-run. Normal runs expect real SonarQube credentials for issue intake.

The default execution mode is `ci`, which means the intended approval gate is GitLab merge request review. If you want an eventual local interactive flow, set `AI_SONAR_BOT_EXECUTION_MODE=local` or change `execution_mode` in [.ai-sonar-bot.json](.ai-sonar-bot.json).

If you explicitly want dry-run to apply the fixture patch locally, set `apply_patch_in_dry_run` to `true` in [.ai-sonar-bot.json](.ai-sonar-bot.json) or set `AI_SONAR_BOT_APPLY_PATCH_IN_DRY_RUN=true`.

## Testing With OpenAI

To test the real LLM path instead of local fixtures, set:

```bash
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-4.1-mini
```

When those are set, dry-run prefers the real OpenAI client over the local analysis and patch fixtures.

For this version, the OpenAI client can also write the returned solution to a file. By default that file is [artifacts/openai-solution.json](artifacts/openai-solution.json), and you can override it with `AI_SONAR_BOT_OPENAI_SOLUTION_OUTPUT_PATH` or `openai_solution_output_path` in [.ai-sonar-bot.json](.ai-sonar-bot.json). In `ci` mode, solution artifacts are disabled by default so merge requests, logs, and state remain the primary traceability surface; set `AI_SONAR_BOT_WRITE_SOLUTION_ARTIFACTS_IN_CI=true` if you want to keep them for debugging.

For v1 safety, the bot only accepts structured edits that touch exactly one file. Multi-file proposals are rejected as out of scope.

## Commands

```bash
uv run ai-sonar-bot dashboard sonar --dry-run
uv run ai-sonar-bot dashboard remediate --dry-run
uv run ai-sonar-bot dashboard reconcile --dry-run
uv run ai-sonar-bot review --dry-run
uv run pytest
PYTHONPATH=src uv run lint-imports
uv run mypy src
uv run ruff check .
uv run ruff format --check .
```

## Pull Request Review V1

The review workflow is GitLab-first and runs from the same image and binary:

```bash
uv run ai-sonar-bot review --dry-run
uv run ai-sonar-bot review
```

Current v1 review scope:

- one merge request per run
- when `CI_MERGE_REQUEST_IID` is present, review only that merge request
- dedup by merge request IID and head SHA
- deterministic summary-note publishing only
- no inline diff comments
- bounded changed-file context with review-specific limits
- draft merge requests skipped by default
- `no_findings` note publishing can be disabled to reduce cost and MR noise

The review workflow uses:

- `GITLAB_URL`
- `GITLAB_TOKEN`
- `GITLAB_PROJECT_ID` or `CI_PROJECT_ID`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

## Docker And GitLab CI

A containerized runtime is included in [Dockerfile](Dockerfile). It installs `uv`, the bot, and the full project dependency set so validation commands such as `uv run pytest` are available when the bot runs inside the repository checkout.

Build the image:

```bash
docker build -t ai-sonar-bot:latest .
```

Run it against a checked-out repository:

```bash
docker run --rm \
  -v "$(pwd):/workspace" \
  --env-file .env \
  ai-sonar-bot:latest
```

The image keeps the installed bot in `/opt/ai-sonar-bot` and uses `/workspace` as the repository root, so mounting another repository does not hide the bot's virtual environment.

## GitHub Releases And GHCR

GitHub release automation is included through:

- [release-please.yml](.github/workflows/release-please.yml)
- [publish-image.yml](.github/workflows/publish-image.yml)
- [release-please-config.json](release-please-config.json)
- [.release-please-manifest.json](.release-please-manifest.json)

How it works:

- merge Conventional Commit messages into `main`
- `release-please` opens or updates a release PR
- when that PR is merged, `release-please` creates a Git tag like `ai-sonar-bot-v0.3.0`
- the created GitHub release or version tag triggers the image publish workflow
- the publish workflow normalizes that tag to semver for GHCR
- GHCR receives tags like `0.3.0`, `0.3`, `0`, and `latest`

If a release already exists and you need to retry publication, the image workflow also supports manual `workflow_dispatch` runs from the GitHub Actions UI. Provide the release tag, for example `ai-sonar-bot-v0.3.0`, so the workflow can publish the correct semver image tags.

The release workflow uses `secrets.RELEASE_PLEASE_TOKEN` instead of the default `GITHUB_TOKEN`. This is intentional: tags and releases created by the default `GITHUB_TOKEN` do not trigger downstream workflows reliably, so the image publish workflow would not run.

Recommended GitHub setup:

- create a fine-grained personal access token or GitHub App token as `RELEASE_PLEASE_TOKEN`
- grant it repository contents and pull request write access
- make the GHCR package public if you want unauthenticated image pulls

After a release tag exists, users can pull a specific version with:

```bash
docker pull ghcr.io/<owner>/ai-sonar-bot:0.2.0
```

An example GitLab pipeline is provided in [.gitlab-ci.example.yml](.gitlab-ci.example.yml). In a target repository, copy that file to `.gitlab-ci.yml` and set these CI variables:

- `SONARQUBE_URL`
- `SONARQUBE_TOKEN`
- `SONARQUBE_PROJECT_KEY`
- `GITLAB_URL`
- `GITLAB_TOKEN`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

`GITLAB_PROJECT_ID` is optional in GitLab CI because the bot falls back to `CI_PROJECT_ID`.

The example now includes four jobs:

- `ai_sonar_bot_dashboard`
  - discovery-only Sonar dashboard sync on the default branch
- `ai_sonar_bot_dashboard_remediate`
  - dashboard-backed remediation on the default branch
- `ai_sonar_bot_dashboard_reconcile`
  - scheduled dashboard reconciliation for `mr_opened` items after merge
    request state changes
- `ai_sonar_bot_review`
  - the merge request review workflow, available as a manual job on `merge_request_event` pipelines or via `RUN_AI_SONAR_BOT_REVIEW=true`

The example overrides the container `entrypoint` to `[""]`. This is required in
GitLab CI because the published image uses `ai-sonar-bot` as its Docker
entrypoint; without the override, the runner shell command is passed to the bot
as if `sh` were a CLI subcommand.

Recommended GitLab CI setup:

- keep dashboard sync as a separate job from active remediation
- keep dashboard-backed remediation as a separate job from dashboard sync
- keep dashboard reconciliation as a separate job from active remediation so it
  only owns post-merge-request lifecycle convergence
- trigger dashboard sync from a pipeline schedule, or manually with `RUN_AI_SONAR_BOT_DASHBOARD=true`
- trigger dashboard-backed remediation from a pipeline schedule, or manually with `RUN_AI_SONAR_BOT_DASHBOARD_REMEDIATE=true`
- trigger dashboard reconciliation from a pipeline schedule, or manually with `RUN_AI_SONAR_BOT_DASHBOARD_RECONCILE=true`
- trigger `ai_sonar_bot_review` from merge request pipelines, or manually with `RUN_AI_SONAR_BOT_REVIEW=true`
- store `SONARQUBE_TOKEN`, `GITLAB_TOKEN`, and `OPENAI_API_KEY` as protected CI variables
- use a token that is allowed to push branches and create merge requests
- keep `GIT_DEPTH=0` so branch and push behavior is predictable
- set a fixed git author and committer identity in the job
- rewrite the `origin` remote in CI to use `GITLAB_TOKEN` for authenticated pushes
- keep review scope narrow with a low `review.max_changed_files`
- set `review.ignored_paths` for generated or low-value areas such as `src/generated/`
- keep `review.max_findings_per_review` low so the bot surfaces only the highest-signal issues
- keep `review.skip_draft_merge_requests` enabled
- set `review.publish_no_findings_note` to `false` if you want lower cost and less MR noise

The dashboard sync job stays separate because it is discovery, not remediation. The dashboard remediation and dashboard reconciliation jobs each use their own `resource_group` so operators can roll them out deliberately without mixing active remediation and post-MR lifecycle convergence. The review job is read-mostly and publishes only merge request notes, so it uses a separate `resource_group`.

Recommended first rollout order:

- run `ai_sonar_bot_dashboard` manually once and confirm eligible Sonar items appear in the dashboard without duplication
- run `ai-sonar-bot dashboard remediate --dry-run` locally to inspect one supported dashboard item without changing lifecycle state
- run one live `dashboard remediate` CI job after dashboard sync and dry-run inspection both behave as expected
- run `ai-sonar-bot dashboard reconcile --dry-run` locally to inspect one `mr_opened` reconciliation decision without changing lifecycle state
- run one live `dashboard reconcile` CI job after a remediation MR is merged or closed
- run `ai_sonar_bot_review` manually on one small merge request pipeline
- enable schedules only after the manual smoke runs for remediation, dashboard sync, dashboard-backed remediation, reconciliation, and review all behave as expected

Dashboard rollout model:

- keep Sonar dashboard sync as the discovery producer for Sonar-derived dashboard items
- treat live `dashboard remediate` as CI-only in the first implementation; use `dashboard remediate --dry-run` locally
- treat live `dashboard reconcile` as CI-only in the first implementation; use `dashboard reconcile --dry-run` locally
- let Sonar sync clean up only stale untouched `open` Sonar items; once remediation has touched an item, preserve its dashboard lifecycle history

## Execution Modes

Local mode:

- creates a branch
- applies and validates the patch
- requests interactive approval before commit when approval is enabled
- commits locally after approval
- does not create a merge request unless you switch to CI mode

CI mode:

- creates a branch
- applies and validates the patch
- commits and pushes the branch
- creates or reuses a GitLab merge request
- uses a deterministic merge request description template with issue traceability and validation details
- reports in the run summary whether the merge request was created or reused
- never blocks for terminal approval

Required GitLab variables for real MR creation:

- `GITLAB_URL`
- `GITLAB_TOKEN`
- `GITLAB_PROJECT_ID` or GitLab CI's built-in `CI_PROJECT_ID`

In GitLab CI, `CI_PROJECT_ID` is used automatically when `GITLAB_PROJECT_ID` is not set.

## Quality Gate

The repository quality pipeline runs in this order:

1. `lint`
2. `architecture`
3. `typecheck`
4. `security`
5. `test`

The test step enforces a minimum total coverage threshold of `80%`.

## Configuration

Copy values from `.env.example` into a local `.env` file and adjust `.ai-sonar-bot.json` for repository-specific behavior. The application loads `.env` automatically.

For CI operation, recovery guidance, and the rollout smoke-test recipes for Sonar remediation, dashboard sync, dashboard-backed remediation, and merge request review, see [runbook.md](docs/runbook.md).
