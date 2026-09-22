FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY app ./app
COPY workers ./workers
COPY migrations ./migrations
COPY alembic.ini ./

RUN uv sync --frozen --no-dev --no-group ml

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]