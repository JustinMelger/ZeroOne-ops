set shell := ["zsh", "-cu"]

sync:
    uv sync --all-groups

lint:
    uv run ruff check .
    uv run ruff format --check .

architecture:
    uv run lint-imports

typecheck:
    uv run mypy src

test:
    uv run pytest

check:
    just lint
    just architecture
    just typecheck
    just test

run:
    uv run ai-sonar-bot run

run-dry:
    uv run ai-sonar-bot run --dry-run
