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

## Execution Modes

Local mode:

- creates a branch
- applies and validates the patch
- commits locally
- does not create a merge request unless you switch to CI mode

CI mode:

- creates a branch
- applies and validates the patch
- commits and pushes the branch
- creates or reuses a GitLab merge request
- reports in the run summary whether the merge request was created or reused

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
4. `test`

The test step enforces a minimum total coverage threshold of `80%`.

## Configuration

Copy values from `.env.example` into a local `.env` file and adjust `.ai-sonar-bot.json` for repository-specific behavior. The application loads `.env` automatically.
