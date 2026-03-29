FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/ai-sonar-bot/.venv \
    PATH="/opt/ai-sonar-bot/.venv/bin:/root/.local/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /opt/ai-sonar-bot

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --all-groups

COPY . .

WORKDIR /workspace

ENTRYPOINT ["uv", "run", "--project", "/opt/ai-sonar-bot", "ai-sonar-bot"]
CMD []
