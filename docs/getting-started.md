# Getting Started

Install ZeroOne Ops in the repository whose findings and changes it will manage.
Choose the templates for that repository's provider; use the files from your
installed release tag rather than assuming `main` matches your image.

## GitHub

Start with the [GitHub control-plane setup](runbook.md#github-control-plane-setup)
and [review workflow example](runbook.md#github-review-workflow-example).
The copyable
[operations](https://github.com/JustinMelger/ZeroOne-ops/blob/main/examples/github-operations.yml),
[review](https://github.com/JustinMelger/ZeroOne-ops/blob/main/examples/github-review.yml),
and [configuration](https://github.com/JustinMelger/ZeroOne-ops/blob/main/examples/.zeroone-ops.github.json)
templates are maintained in the repository.

## GitLab

Follow the [recommended GitLab CI setup](runbook.md#recommended-gitlab-ci-setup).
Use the supported
[CI template](https://github.com/JustinMelger/ZeroOne-ops/blob/main/examples/.gitlab-ci.example.yml)
and [configuration example](https://github.com/JustinMelger/ZeroOne-ops/blob/main/examples/.zeroone-ops.json).
The repository owns scanner production and optional MyPy-to-SARIF conversion.

## Before Enabling Schedules

Configure the [required variables](runbook.md#required-ci-variables) and
[least-privilege token permissions](runbook.md#required-token-permissions).
Read the [execution trust model](runbook.md#execution-trust-model): setup and
validation commands are executable CI policy, not passive scanner data.

Run the [remediation smoke test](runbook.md#smoke-test-recipe) and
[review smoke test](runbook.md#review-smoke-test-recipe) manually before enabling
recurring execution. Existing pre-v1 installations must first follow the
[migration guide](migration-v1.md).
