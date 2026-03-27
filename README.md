# AI Sonar Bot

AI Sonar Bot is a Python CLI that will fetch open SonarQube issues, analyze one issue, prepare a fix, validate the change, and create a GitLab merge request after human approval.

## Status

This repository currently contains:

- functional and technical design documents,
- a Python project scaffold,
- configuration and state models,
- a dry-run capable CLI and runner skeleton.

Provider integrations for SonarQube, GitLab, and the LLM are still stubbed.

## Tooling

- `uv` for environment and dependency management
- `ruff` for linting and formatting
- `mypy` for static type checking
- `pytest` and `pytest-cov` for tests and coverage
- `import-linter` for architecture boundary checks

## Getting Started

```bash
uv sync
uv run ai-sonar-bot run --dry-run
```

## Dry-Run With Fixture Data

When the repository is not connected to a real SonarQube project yet, dry-run can use a local fixture file instead.

The scaffold includes [fixtures/sonar/issues.json](/Users/justinmelger/Desktop/github/ai-sonar-bot/fixtures/sonar/issues.json), and `.ai-sonar-bot.json` points to it by default through `mock_sonar_issues_path`.

This fixture mode is only used during dry-run. Normal runs still expect real SonarQube credentials.

## Commands

```bash
uv run ai-sonar-bot run
uv run ai-sonar-bot run --dry-run
uv run pytest
uv run lint-imports
uv run mypy src
uv run ruff check .
uv run ruff format --check .
```

## Configuration

Copy values from `.env.example` into a local `.env` file and adjust `.ai-sonar-bot.json` for repository-specific behavior. The application loads `.env` automatically.
