FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY app ./app
COPY workers ./workers
COPY ml ./ml

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

CMD ["celery", "-A", "workers.celery_app", "worker", "--loglevel=info"]