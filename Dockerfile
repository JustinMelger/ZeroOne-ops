FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/zeroone-ops/.venv \
    PATH="/root/.local/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /opt/zeroone-ops

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-editable


FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/zeroone-ops/.venv/bin:${PATH}" \
    HOME="/home/zeroone"

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 zeroone \
    && useradd --uid 10001 --gid zeroone --create-home --shell /usr/sbin/nologin zeroone \
    && mkdir -p /opt/zeroone-ops /workspace \
    && chown -R zeroone:zeroone /workspace \
    && git config --system --add safe.directory /workspace

COPY --from=builder --chown=zeroone:zeroone /opt/zeroone-ops /opt/zeroone-ops

WORKDIR /workspace

USER zeroone

ENTRYPOINT ["/opt/zeroone-ops/.venv/bin/zeroone-ops"]
CMD []
