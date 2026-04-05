# AGENT.md

## Purpose

This file is the quick-start guide for contributors and coding agents working in
this repository.

The source of truth for coding and architecture rules is:

- [docs/engineering-standards.md](/Users/justinmelger/Desktop/github/ai-sonar-bot/docs/engineering-standards.md)

When there is any ambiguity, follow that document over this summary.

## Repository Intent

This repository contains a GitLab-first automation platform that currently
ships:

- a SonarQube remediation workflow
- a pull request review workflow

The codebase is intentionally structured to keep domain logic testable and
maintainable as new workflows are added.

## Working Rules

- Keep changes small, explicit, and easy to review.
- Prefer extending existing domain concepts over adding parallel patterns.
- Add abstractions only when they remove real duplication or isolate real
  variability.
- Keep business logic out of `cli.py`.
- Keep `runner.py` as a composition root, not a catch-all implementation file.
- Push external API, filesystem, and subprocess details to provider or focused
  service layers.
- Use typed models for data crossing service boundaries.
- Add or update tests with behavior changes, especially for regressions.

## Layering Summary

- `models`
  - typed domain and configuration models only
- `providers`
  - external system adapters only
- `services`
  - focused application behavior and orchestration
- `runner`
  - high-level workflow composition
- `cli`
  - argument parsing and terminal output only

Do not introduce imports that violate those boundaries.

## Coding Expectations

- Prefer simple, explicit code over clever abstractions.
- Favor composition over inheritance.
- Keep constructors cheap and side-effect free.
- Avoid hidden environment access outside `settings.py`.
- Use Google-style docstrings for public modules, classes, and functions.
- Keep comments rare and intent-focused.
- Use domain names, not vague placeholders like `data`, `item`, or `helper`.

## Testing Expectations

- Mirror the source tree under `tests/`.
- Prefer unit tests for policy and transformation logic.
- Use integration tests for runner and provider wiring.
- Add regression coverage for bug fixes when practical.

## Before Finishing

Run the relevant checks for code changes:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
```

If you are changing workflow docs or CI behavior, also update the relevant
documentation:

- [README.md](/Users/justinmelger/Desktop/github/ai-sonar-bot/README.md)
- [docs/runbook.md](/Users/justinmelger/Desktop/github/ai-sonar-bot/docs/runbook.md)
- [docs/roadmap.md](/Users/justinmelger/Desktop/github/ai-sonar-bot/docs/roadmap.md)
