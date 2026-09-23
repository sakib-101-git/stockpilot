# Stockpilot

![CI](https://github.com/sakib-101-git/stockpilot/actions/workflows/ci.yml/badge.svg)

An AI-powered inventory and demand platform for small retailers: probabilistic
demand forecasting, budget-constrained reorder recommendations, and an
explainable assistant, built with Python and FastAPI.

**Status:** under construction (Weeks 1-9 done; 10 next).

## What it does

Stockpilot ingests a shop's sales as they happen, forecasts demand per
product 28 days out with calibrated uncertainty, and turns those forecasts
into concrete purchasing decisions: when to reorder, how much, and, when
budget is limited, which products to prioritize. Every part of that
pipeline is tenant-isolated, tested against a real Postgres and Redis, and
built to be explainable rather than a black box.

## What works so far

**Multi-tenant API.** Each shop is a tenant, each user belongs to one.
Registration and login use Argon2 password hashing and JWT access tokens.
Roles (owner, staff) are enforced server-side, with 401 and 403 kept
distinct. Tenant isolation is enforced in two independent layers: query
filters in application code, and Postgres row-level security in the
database itself. Tests prove that a forgotten filter in the code still
cannot leak another tenant's data.

**Background jobs.** CSV product import runs as a Celery task rather than
inline in the request. Every row is validated individually, so bad rows
are reported without blocking the good ones. Suppliers, costs, lead
times, opening stock, and FOODS batch/expiry data are generated
synthetically, since none of it exists in the underlying M5 sales data
(see `docs/decisions/0007-synthetic-supply-data.md`). The API and worker
run as separate Docker images, so ML libraries never ship inside the
API's deployed container.

**Live sales pipeline.** A Redis Streams consumer turns sales events into
`stock_movements` rows, with idempotent processing (a redelivered event
is never double-counted), bounded retries, and a dead-letter stream for
events that keep failing. A replay script simulates a live point-of-sale
feed from the M5 sample's historical sales; the current dev database has
replayed 188,014 real events through this exact pipeline. Details in
`docs/decisions/0008-redis-streams-consumer.md`.

**Forecasting.** A rolling-origin backtest (six folds, 28-day horizon,
spanning two Christmas seasons) with explicit leakage tests. A weighted
LightGBM model matches the best statistical baseline on RMSSE (0.712
against 0.709 for AutoETS) and cuts pooled RMSE by about 3% (1.979
against 2.040), winning on that measure in all six folds, though it loses
clearly on the December 2014 fold. Quantile LightGBM models give a
90th-percentile upper bound per forecast: pinball loss is 4.6% lower than
a simple history-based bound, and 9.6% of real outcomes exceed it against
a 10% target. Full results in `docs/experiments.md` and `docs/decisions/`.

**Nightly forecast generation.** A Celery Beat schedule retrains and
forecasts from each tenant's real, event-sourced `stock_movements`
history, not a static file, registers and versions every model through
MLflow, and writes results to a `forecasts` table that keeps history
rather than overwriting it. Served through the API
(`GET /products/{id}/forecast`, `GET /forecasts/summary`), with an
on-demand SHAP explanation endpoint
(`GET /products/{id}/forecast/{date}/explain`) showing which features
drove a given prediction. Details in
`docs/decisions/0009-nightly-forecast-generation.md`.

**Reorder recommendations and budget optimization.** A reorder point is
computed directly from the calibrated 90th-percentile forecast, buffered
for lead-time uncertainty, and rounded to each supplier's pack size and
minimum order quantity (`GET /products/{id}/reorder`). When purchasing
budget is limited, a 0/1 knapsack solved with OR-Tools chooses which
products to fully reorder to maximize stockout-risk coverage within that
budget (`GET /optimize-budget`). Details in
`docs/decisions/0010-reorder-optimizer.md`.

**Infrastructure.** Alembic migrations, a test suite that runs against a
real Postgres and Redis rather than mocks, and CI on every push covering
linting, formatting, and the full test suite.

## Quick start

Requires Docker, [uv](https://docs.astral.sh/uv/), and Python 3.12.

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

To load the sample's products and synthetic supplier/cost/stock data into
a tenant's database, once the tenant and its products exist:

```bash
uv run python -m scripts.synth.load_products
uv run python -m scripts.synth.seed
```

## Design decisions

See [`docs/decisions/`](docs/decisions/) for short notes on the main
technical choices and their trade-offs, including where the current data
has known, stated limitations, and
[`docs/experiments.md`](docs/experiments.md) for the full forecasting
experiment log.
