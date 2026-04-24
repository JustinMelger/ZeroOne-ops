# ZeroOne Ops

AI-powered code maintenance and remediation.

Automate the detection, review, and fixing of code issues.

Naming note:

- product brand: `ZeroOne Ops`
- technical release and image slug: `zeroone-ops`
- legacy compatibility aliases still work for config and environment variables during the transition, but operator-facing examples now use the `ZeroOne Ops` names everywhere.

## Current Scope

The current v1 scope includes:

- SonarQube issue intake and selection
- dashboard-backed remediation and reconciliation workflows
- GitLab merge request review
- focused code-context gathering and LLM-backed analysis
- patch generation, validation, and MR creation in CI mode
- a conservative single-file remediation boundary for safety

This repository is in an active testing and hardening period. The main goal is
stable operator workflows and useful review quality, not broad feature
expansion.

## Quick Start

```bash
uv sync
uv run zeroone-ops dashboard sonar --dry-run
uv run zeroone-ops dashboard remediate --dry-run
uv run zeroone-ops review --dry-run
```

Useful quality commands:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
just architecture
```

## Core Workflows

### Dashboard Remediation

- sync SonarQube findings into the dashboard
- select one supported item per run
- generate and validate a bounded fix
- create or reuse a GitLab merge request in CI mode

### Dashboard Reconciliation

- inspect `mr_opened` dashboard items
- update lifecycle state after merge request outcomes change
- keep reconciliation separate from active remediation

### Merge Request Review

- review one merge request per run
- publish one deterministic summary note per reviewed revision
- deduplicate by merge request IID and head SHA
- avoid inline comments in v1

## Dry-Run And Fixtures

Dry-run can use local fixtures before a repository is connected to real
services.

Included fixtures:

- [fixtures/sonar/issues.json](fixtures/sonar/issues.json)
- [fixtures/llm/analysis.json](fixtures/llm/analysis.json)
- [fixtures/llm/edit.json](fixtures/llm/edit.json)
- [samples/auto_fixable_example.py](samples/auto_fixable_example.py)

The repository's current default config file is
[.zeroone-ops.json](.zeroone-ops.json).
Copyable operator examples now live in [examples/](examples/), including:

- [examples/.zeroone-ops.json](examples/.zeroone-ops.json)
- [examples/.env.example](examples/.env.example)
- [examples/.gitlab-ci.example.yml](examples/.gitlab-ci.example.yml)

Use the root [.zeroone-ops.json](.zeroone-ops.json) as the repository's live
runtime config, and use the files in [examples/](examples/) as copyable
templates when wiring the bot into another repository.

To test the real OpenAI path instead of local fixtures:

```bash
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-4.1-mini
```

For v1 safety, remediation only accepts structured edits that touch exactly one
file.

## Credentials And Secrets

For local testing, the most common environment variables are:

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `GITLAB_URL`
- `GITLAB_TOKEN`
- `SONARQUBE_URL`
- `SONARQUBE_TOKEN`
- `SONARQUBE_PROJECT_KEY`

Store CI secrets as masked and protected variables, and avoid shell tracing
around authenticated git remote rewrites. Use the runbook for workflow-by-
workflow token requirements and permission guidance.

## Container And Releases

Build the local image:

```bash
docker build -t zeroone-ops:latest .
```

Run it against a checked-out repository:

```bash
docker run --rm \
  -v "$(pwd):/workspace" \
  --env-file .env \
  zeroone-ops:latest
```

The image keeps the installed bot in `/opt/zeroone-ops` and uses `/workspace`
as the repository root, so mounting another repository does not hide the bot's
virtual environment.

GitHub release automation uses `release-please` plus the publish workflow.
Stable release tags now follow the `zeroone-ops-vX.Y.Z` pattern.
Prerelease tags can use `zeroone-ops-vX.Y.Z-rc.N`; those publish explicit
prerelease image tags without updating `latest`, while the workflow still
accepts older tag prefixes during transition.

Pull a published image with:

```bash
docker pull ghcr.io/<owner>/zeroone-ops:0.2.0
```

A GitLab CI example is provided in
[examples/.gitlab-ci.example.yml](examples/.gitlab-ci.example.yml). It uses the
published `zeroone-ops` image while keeping the current runtime command names.

## Execution Modes

Local mode:

- creates a branch
- applies and validates the patch
- can request interactive approval before commit
- does not create a merge request unless you switch to CI mode

CI mode:

- creates a branch
- applies and validates the patch
- pushes the branch
- creates or reuses a GitLab merge request
- never blocks for terminal approval

## Docs

Use these docs for the deeper operational details:

- [docs/runbook.md](docs/runbook.md) for CI setup, credentials, rollout order,
  and smoke-test recipes
- [docs/roadmap.md](docs/roadmap.md) for current build, hardening, and rebrand
  sequencing
- [docs/functional-design-pr-review.md](docs/functional-design-pr-review.md)
  and [docs/technical-design-pr-review.md](docs/technical-design-pr-review.md)
  for the review workflow design
- [future_plans.md](future_plans.md) for post-v1 ideas
