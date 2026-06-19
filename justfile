set shell := ["zsh", "-cu"]

sync:
    uv sync --all-groups

lint:
    uv run ruff check .
    uv run ruff format --check .

architecture:
    PYTHONPATH=src uv run lint-imports

typecheck:
    uv run mypy src

security:
    uv run pip-audit --ignore-vuln PYSEC-2026-196 --ignore-vuln GHSA-537c-gmf6-5ccf --ignore-vuln GHSA-6v7p-g79w-8964
    uv run bandit -r src

test:
    uv run pytest

check:
    just lint
    just architecture
    just typecheck
    just security
    just test

run:
    uv run zeroone-ops dashboard remediate

run-dry:
    uv run zeroone-ops dashboard remediate --dry-run
