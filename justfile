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
    uv run pip-audit
    uv run bandit -r src

test:
    uv run pytest

test-scenarios:
    uv run --no-sync pytest tests/zeroone_ops/integration/scenarios --no-cov

docs-serve:
    uv run --locked --only-group docs zensical serve

docs-build:
    uv run --locked --only-group docs zensical build --clean --strict

check:
    just lint
    just architecture
    just typecheck
    just security
    just test

run:
    uv run zeroone-ops remediation run

run-dry:
    uv run zeroone-ops remediation run --dry-run
