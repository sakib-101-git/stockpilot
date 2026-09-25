FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY app ./app
COPY workers ./workers
COPY ml ./ml
COPY data/processed ./data/processed

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
ENV STOCKPILOT_WORKER_PROCESS=1

CMD ["celery", "-A", "workers.celery_app", "worker", "--loglevel=info", "--pool=solo"]
