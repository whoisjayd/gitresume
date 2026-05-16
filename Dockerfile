FROM ghcr.io/astral-sh/uv:0.9.18-python3.12-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev

FROM node:24-bookworm-slim AS node-runtime

FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN addgroup --system appgroup \
    && adduser --system --home /home/appuser --ingroup appgroup appuser \
    && mkdir -p /home/appuser/.npm /home/appuser/.config/litellm \
    && chown -R appuser:appgroup /home/appuser

COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --from=node-runtime /usr/local/ /usr/local/
COPY --chown=appuser:appgroup pyproject.toml README.md ./
COPY --chown=appuser:appgroup src ./src

ENV PATH="/app/.venv/bin:$PATH" \
    HOME=/home/appuser \
    NPM_CONFIG_CACHE=/home/appuser/.npm \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8080/api/health || exit 1

CMD ["uvicorn", "gitresume.main:app", "--host", "0.0.0.0", "--port", "8080"]
