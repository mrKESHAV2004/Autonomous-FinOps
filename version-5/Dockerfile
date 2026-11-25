# Local development image for the web app and the worker (see docker-compose.yml).
# Production hardening (gunicorn, image scanning) comes with Phase 6.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --extra postgres
COPY alembic.ini ./
COPY src ./src
RUN uv sync --frozen --extra postgres \
    && useradd --create-home --uid 1000 finops \
    && mkdir -p /data/uploads && chown -R finops /data

ENV PATH="/app/.venv/bin:$PATH" \
    FINOPS_UPLOAD_DIR=/data/uploads \
    FINOPS_ARTIFACT_DIR=/data/artifacts \
    FINOPS_HOST=0.0.0.0

USER finops
EXPOSE 5000
CMD ["finops-web"]
