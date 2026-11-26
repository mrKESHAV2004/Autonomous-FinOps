# Multi-stage production build for Autonomous FinOps.
# Stage 1: Build virtual environment with uv
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --extra postgres --extra ml
COPY alembic.ini ./
COPY src ./src
RUN uv sync --frozen --extra postgres --extra ml

# Stage 2: Runtime image (unprivileged user, non-root)
FROM python:3.12-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    FINOPS_UPLOAD_DIR=/data/uploads \
    FINOPS_ARTIFACT_DIR=/data/artifacts \
    FINOPS_HOST=0.0.0.0 \
    FINOPS_PORT=5000

RUN groupadd --gid 1000 finops \
    && useradd --create-home --uid 1000 --gid 1000 finops \
    && mkdir -p /data/uploads /data/artifacts \
    && chown -R finops:finops /data

WORKDIR /app
COPY --from=builder --chown=finops:finops /app/.venv /app/.venv
COPY --chown=finops:finops alembic.ini pyproject.toml ./
COPY --chown=finops:finops src ./src

USER finops
EXPOSE 5000

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/healthz')" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--threads", "2", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "finops_app:create_app()"]
