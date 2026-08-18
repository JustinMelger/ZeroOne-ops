# AGENTS.md

## Purpose

This file is the quick-start guide for contributors and coding agents working in
this repository.

The source of truth for coding and architecture rules is:

- [docs/engineering-standards.md](docs/engineering-standards.md)

When there is any ambiguity, follow that document over this summary.

Current workflow behavior and future direction are documented in:

- [docs/README.md](docs/README.md)
- [docs/roadmap.md](docs/roadmap.md)
- [docs/design/README.md](docs/design/README.md)
- [docs/design/functional/functional-design-finding-ingestion.md](docs/design/functional/functional-design-finding-ingestion.md)
- [docs/design/technical/technical-design-finding-ingestion.md](docs/design/technical/technical-design-finding-ingestion.md)
- [docs/design/functional/functional-design-work-item-state-projection.md](docs/design/functional/functional-design-work-item-state-projection.md)
- [docs/design/technical/technical-design-work-item-state-projection.md](docs/design/technical/technical-design-work-item-state-projection.md)
- [docs/design/functional/functional-design-remediation-recovery.md](docs/design/functional/functional-design-remediation-recovery.md)
- [docs/design/technical/technical-design-remediation-recovery.md](docs/design/technical/technical-design-remediation-recovery.md)
- [docs/design/functional/functional-design-pr-review-staged-pipeline.md](docs/design/functional/functional-design-pr-review-staged-pipeline.md)

Older dashboard and GitLab-first design documents preserve implementation
history. Do not treat them as current product direction unless a compatibility
change explicitly targets legacy dashboard mode.

Operational feedback and longer-horizon research/planning now live in Notion.
Keep the repo focused on current roadmap, implementation contracts, and design
truth.

## Repository Intent

ZeroOne Ops is a GitLab- and GitHub-compatible control plane for governed
OpenAI-assisted engineering workflows. It currently ships:

- staged change-request review with durable continuity evidence
- normalized finding ingestion from SonarQube and SARIF-based sources
- policy, work-item, remediation, recovery, lifecycle, and operational-summary
  workflows using provider-native issues and change requests

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
- Treat repository configuration that invokes setup or validation commands as
  executable CI policy. Do not weaken its trusted-default-branch or
  least-privilege execution boundary without an explicit design change.
- GitLab dashboard mode is deprecated compatibility behavior. Keep new
  control-plane behavior in GitHub/GitLab issue mode unless a design explicitly
  requires dashboard support.

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

## Workflow Boundary Review

After each workflow-affecting implementation slice, do a short boundary review
before considering the work complete.

Check that:

- workflow ownership still matches the current design docs
- remediation, review, reconciliation, and dashboard state did not silently
  take over each other's responsibilities
- operator-facing surfaces and machine-facing state are still clearly separated
- any real boundary change is reflected in the relevant design and runbook docs

For stateful work-item changes, preserve this separation:

- finding sync owns inventory and policy/capacity projection
- remediation owns execution outcomes and linked change requests
- lifecycle owns provider-native change-request terminal reconciliation
- provider labels are indexes; persisted machine state remains authoritative

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
- keep actionable findings self-contained but bounded: state the affected
  behavior, concise cause and impact, scoped fix, and relevant locations;
  reserve expanded causal walkthroughs for cross-flow or behavior-sensitive
  changes

## Required Verification

After every repository code change, run the required checks before considering
the task complete:

```bash
uv run ruff check .
just architecture
uv run mypy src
uv run bandit -q -r src
uv run pytest
```

For docs-only or example-config-only changes, use judgment and report which
checks were intentionally skipped.

Do not treat the task as complete until the required checks pass, or you have
explicitly reported which check could not be run and why.

If you are changing workflow docs or CI behavior, also update the relevant
documentation:

- [README.md](README.md)
- [docs/runbook.md](docs/runbook.md)
- [docs/roadmap.md](docs/roadmap.md)
