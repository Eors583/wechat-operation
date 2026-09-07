FROM python:3.12-slim AS base

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG UV_DEFAULT_INDEX=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT="/opt/venv" \
    UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX}" \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir uv

FROM base AS development
RUN uv sync --frozen --all-groups

COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY retrieval-schema.sql ./retrieval-schema.sql
COPY tests ./tests
COPY alembic.ini ./alembic.ini

USER appuser
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM development AS test
CMD ["uv", "run", "pytest"]

FROM base AS runtime
RUN uv sync --frozen --no-dev

COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY retrieval-schema.sql ./retrieval-schema.sql
COPY alembic.ini ./alembic.ini

USER appuser
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
