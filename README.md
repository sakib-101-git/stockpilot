# Stockpilot

![CI](https://github.com/sakib-101-git/stockpilot/actions/workflows/ci.yml/badge.svg)

AI-powered inventory and demand platform: probabilistic demand forecasting,
order recommendations, and an explainable assistant, built with Python and
FastAPI.

**Status:** under construction (Weeks 1-8 done; 9 next).

## What works so far

- Multi-tenant API: each shop is a tenant, and each user belongs to one.
- Registration and login with Argon2 password hashing and JWT access tokens.
- Roles (owner, staff) enforced on the server, with 401 and 403 kept apart.
- Tenant-scoped products and suppliers with pagination.
- Tenant isolation in two layers: query filters in the code, and Postgres
  row-level security in the database. Tests prove that a forgotten filter
  cannot leak data.
- Background jobs: CSV product import runs as a Celery task, not inline in
  the request. Every row is validated, bad rows are reported individually
  without blocking good ones, and writes are tenant-scoped through row-level
  security. Suppliers, costs, lead times, opening stock, and FOODS batch/
  expiry data are generated synthetically (documented in
  `docs/decisions/0007-synthetic-supply-data.md`) since none of it exists in
  the M5 source data. Separate Docker images for the API and worker keep
  ML libraries (lightgbm, scikit-learn, statsforecast) out of the API's
  deployed image.
- Live sales pipeline: a Redis Streams consumer turns sales events into
  stock_movements rows, with idempotent processing (a redelivered event is
  never double-counted), bounded retries, and a dead-letter stream for
  events that keep failing. A replay script simulates a live feed from the
  M5 sample's historical sales, since no real point-of-sale integration
  exists. Details in `docs/decisions/0008-redis-streams-consumer.md`.
- Forecasting: rolling-origin backtest (six folds, 28-day horizon, two
  Christmas windows) with leakage tests. A weighted LightGBM matches the best
  statistical baselines on RMSSE (0.712 against 0.709 for AutoETS) and cuts
  pooled RMSE by about 3% (1.979 against 2.040), winning that measure in all
  six folds. It loses clearly on the December 2014 fold. Details in
  `docs/experiments.md` and `docs/decisions/`.
- Prediction intervals: quantile LightGBM models give a 90th-percentile upper
  bound for each forecast. Pinball loss is 4.6% lower than a simple
  history-based bound over six folds, and 9.6% of outcomes exceed it (target
  10%). For medium and slow series the lower end is zero, so it is a one-sided
  bound. A separate fallback handles products with little history.
- Nightly forecast generation: a Celery Beat schedule trains and forecasts
  from each tenant's real, event-sourced `stock_movements` history (not the
  static M5 sample), registers and versions every model via MLflow, and
  writes the results to a `forecasts` table that keeps history rather than
  overwriting it. Served through the API (`GET /products/{id}/forecast`,
  `GET /forecasts/summary`), with an on-demand SHAP explanation endpoint
  (`GET /products/{id}/forecast/{date}/explain`) showing which features
  drove a given prediction. Details in
  `docs/decisions/0009-nightly-forecast-generation.md`.
- Alembic migrations, and a test suite that runs against a real Postgres.
- CI on every push: lint, formatting, and tests with Postgres and Redis.

## Quick start

Requires Docker, [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
cp .env.example .env
# put a random value in JWT_SECRET_KEY, for example: openssl rand -hex 32
make up        # start Postgres (TimescaleDB) and Redis
make migrate   # apply migrations (also creates the restricted app role)
make run       # start the API on http://localhost:8000
```

Open http://localhost:8000/docs for the interactive API docs.

To also run the background worker (needed for CSV import and forecasting):

```bash
make worker
```

To run the nightly forecast scheduler:

```bash
uv run celery -A workers.celery_app beat --loglevel=info
```

To run the stream consumer (needed for the live sales pipeline):

```bash
uv run python -m workers.stream_consumer
```

To replay the M5 sample as simulated live sales:

```bash
uv run python -m scripts.synth.replay --limit 100
```

To run the API and worker as Docker containers instead of locally:

```bash
docker compose up -d api worker
```

The containerized API is served on http://localhost:8001.

## Running the tests

Tests use a separate database so they never touch development data.

```bash
docker compose exec db psql -U stockpilot -d stockpilot -c "CREATE DATABASE stockpilot_test;"
make test
```

## Building the dataset

Stockpilot uses a sample of the M5 (Walmart) dataset.

1. Download the data from https://www.kaggle.com/c/m5-forecasting-accuracy
   and unzip it into `data/raw/m5/`.
2. Run `uv run python scripts/prepare_m5.py`.

To load the sample's products and synthetic supplier/cost/stock data into a
tenant's database (after the tenant and its products exist):

```bash
uv run python -m scripts.synth.load_products
uv run python -m scripts.synth.seed
```

## Design decisions

See [`docs/decisions/`](docs/decisions/) for short notes on the main technical
choices and their trade-offs, and [`docs/experiments.md`](docs/experiments.md)
for the forecasting experiment log.
