# AGENT.md

## Purpose

This file is the quick-start guide for contributors and coding agents working in
this repository.

The source of truth for coding and architecture rules is:

- [docs/engineering-standards.md](docs/engineering-standards.md)

When there is any ambiguity, follow that document over this summary.

Current workflow behavior and future direction are documented in:

- [docs/functional-design.md](docs/functional-design.md)
- [docs/technical-design.md](docs/technical-design.md)
- [docs/functional-design-pr-review.md](docs/functional-design-pr-review.md)
- [docs/technical-design-pr-review.md](docs/technical-design-pr-review.md)
- [docs/functional-design-dashboard.md](docs/functional-design-dashboard.md)
- [docs/functional-design-dashboard-remediation.md](docs/functional-design-dashboard-remediation.md)
- [docs/technical-design-dashboard.md](docs/technical-design-dashboard.md)
- [docs/technical-design-dashboard-remediation.md](docs/technical-design-dashboard-remediation.md)
- [future_plans.md](future_plans.md)

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

## Review Expectations

When reviewing changes in this repository:

- check that layering rules are still respected
- check that new logic is placed in the right model, provider, service, runner,
  or CLI layer
- check that tests cover behavior changes and regressions
- check that the required verification commands were run
- check that workflow, CI, or operator-facing behavior changes update the
  relevant docs
- prefer findings tied to repository rules and behavioral risk over generic
  style commentary

## Required Verification

After every repository change, run the required checks before considering the
task complete:

```bash
uv run ruff check .
just architecture
uv run mypy src
uv run pytest
```

Do not treat the task as complete until these checks pass, or you have
explicitly reported which check could not be run and why.

If you are changing workflow docs or CI behavior, also update the relevant
documentation:

- [README.md](README.md)
- [docs/runbook.md](docs/runbook.md)
- [docs/roadmap.md](docs/roadmap.md)
