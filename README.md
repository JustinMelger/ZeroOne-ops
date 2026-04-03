# AI Sonar Bot

AI Sonar Bot is a Python CLI that fetches open SonarQube issues, analyzes one issue, prepares a fix, validates the change, and creates a GitLab merge request for human review.

## Status

This repository currently contains:

- functional and technical design documents,
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

## Tooling

- `uv` for environment and dependency management
- `ruff` for linting and formatting
- `mypy` for static type checking
- `pytest` and `pytest-cov` for tests and coverage
- `import-linter` for architecture boundary checks

## Getting Started

```bash
uv sync
uv run ai-sonar-bot --dry-run
```

## Dry-Run With Fixture Data

When the repository is not connected to a real SonarQube project yet, dry-run can use a local fixture file instead.

The scaffold includes [fixtures/sonar/issues.json](/Users/justinmelger/Desktop/github/ai-sonar-bot/fixtures/sonar/issues.json), and `.ai-sonar-bot.json` points to it by default through `mock_sonar_issues_path`.
The default Sonar fixture now targets [samples/auto_fixable_example.py](/Users/justinmelger/Desktop/github/ai-sonar-bot/samples/auto_fixable_example.py), which is intentionally simple so the real OpenAI dry-run has an auto-fixable test case.

For analysis-only dry-runs, the scaffold also includes [fixtures/llm/analysis.json](/Users/justinmelger/Desktop/github/ai-sonar-bot/fixtures/llm/analysis.json) through `mock_llm_analysis_path`.

For patch-proposal dry-runs, the scaffold also includes [fixtures/llm/patch.json](/Users/justinmelger/Desktop/github/ai-sonar-bot/fixtures/llm/patch.json) through `mock_llm_patch_path`.

This fixture mode is only used during dry-run. Normal runs expect real SonarQube credentials for issue intake.

The default execution mode is `ci`, which means the intended approval gate is GitLab merge request review. If you want an eventual local interactive flow, set `AI_SONAR_BOT_EXECUTION_MODE=local` or change `execution_mode` in [.ai-sonar-bot.json](/Users/justinmelger/Desktop/github/ai-sonar-bot/.ai-sonar-bot.json).

If you explicitly want dry-run to apply the fixture patch locally, set `apply_patch_in_dry_run` to `true` in [.ai-sonar-bot.json](/Users/justinmelger/Desktop/github/ai-sonar-bot/.ai-sonar-bot.json) or set `AI_SONAR_BOT_APPLY_PATCH_IN_DRY_RUN=true`.

## Testing With OpenAI

To test the real LLM path instead of local fixtures, set:

```bash
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-4.1-mini
```

When those are set, dry-run prefers the real OpenAI client over the local analysis and patch fixtures.

For this version, the OpenAI client also writes the returned solution to a file. By default that file is [artifacts/openai-solution.json](/Users/justinmelger/Desktop/github/ai-sonar-bot/artifacts/openai-solution.json), and you can override it with `AI_SONAR_BOT_OPENAI_SOLUTION_OUTPUT_PATH` or `openai_solution_output_path` in [.ai-sonar-bot.json](/Users/justinmelger/Desktop/github/ai-sonar-bot/.ai-sonar-bot.json).

## Commands

```bash
uv run ai-sonar-bot
uv run ai-sonar-bot --dry-run
uv run pytest
uv run lint-imports
uv run mypy src
uv run ruff check .
uv run ruff format --check .
```

## Docker And GitLab CI

A containerized runtime is included in [Dockerfile](/Users/justinmelger/Desktop/github/ai-sonar-bot/Dockerfile). It installs `uv`, the bot, and the full project dependency set so validation commands such as `uv run pytest` are available when the bot runs inside the repository checkout.

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

- [release-please.yml](/Users/justinmelger/Desktop/github/ai-sonar-bot/.github/workflows/release-please.yml)
- [publish-image.yml](/Users/justinmelger/Desktop/github/ai-sonar-bot/.github/workflows/publish-image.yml)
- [release-please-config.json](/Users/justinmelger/Desktop/github/ai-sonar-bot/release-please-config.json)
- [.release-please-manifest.json](/Users/justinmelger/Desktop/github/ai-sonar-bot/.release-please-manifest.json)

How it works:

- merge Conventional Commit messages into `main`
- `release-please` opens or updates a release PR
- when that PR is merged, `release-please` creates a Git tag like `v0.2.0`
- the created GitHub release or version tag triggers the image publish workflow
- GHCR receives tags like `0.2.0`, `0.2`, `0`, and `latest`

If a release already exists and you need to retry publication, the image workflow also supports manual `workflow_dispatch` runs from the GitHub Actions UI.

The release workflow uses `secrets.RELEASE_PLEASE_TOKEN` instead of the default `GITHUB_TOKEN`. This is intentional: tags and releases created by the default `GITHUB_TOKEN` do not trigger downstream workflows reliably, so the image publish workflow would not run.

Recommended GitHub setup:

- create a fine-grained personal access token or GitHub App token as `RELEASE_PLEASE_TOKEN`
- grant it repository contents and pull request write access
- make the GHCR package public if you want unauthenticated image pulls

After a release tag exists, users can pull a specific version with:

```bash
docker pull ghcr.io/<owner>/ai-sonar-bot:0.2.0
```

An example GitLab pipeline is provided in [.gitlab-ci.example.yml](/Users/justinmelger/Desktop/github/ai-sonar-bot/.gitlab-ci.example.yml). In a target repository, copy that file to `.gitlab-ci.yml` and set these CI variables:

- `SONARQUBE_URL`
- `SONARQUBE_TOKEN`
- `SONARQUBE_PROJECT_KEY`
- `GITLAB_URL`
- `GITLAB_TOKEN`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

`GITLAB_PROJECT_ID` is optional in GitLab CI because the bot falls back to `CI_PROJECT_ID`.

Recommended GitLab CI setup:

- keep the bot job restricted to the default branch
- trigger it from a pipeline schedule, or manually with `RUN_AI_SONAR_BOT=true`
- store `SONARQUBE_TOKEN`, `GITLAB_TOKEN`, and `OPENAI_API_KEY` as protected CI variables
- use a token that is allowed to push branches and create merge requests
- keep `GIT_DEPTH=0` so branch and push behavior is predictable
- set a fixed git author and committer identity in the job
- rewrite the `origin` remote in CI to use `GITLAB_TOKEN` for authenticated pushes

The example pipeline now does all of the above and also uses a `resource_group` so two bot jobs do not try to mutate the same repository checkout at once.

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
