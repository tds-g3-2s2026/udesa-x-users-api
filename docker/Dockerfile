# Build stage: uv resolves and installs dependencies into an isolated venv.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Dependencies are installed before copying the source so the layer cache
# survives any change under src/.
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

COPY src/ ./src/
RUN uv sync --no-dev

# Final stage: only the venv and the source, without uv or build tooling.
FROM python:3.13-slim

RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app
EXPOSE 8000

# One worker per process: scaling is the orchestrator's job. With several workers
# inside the container, a hung one goes unnoticed by every probe.
CMD ["uvicorn", "users_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
