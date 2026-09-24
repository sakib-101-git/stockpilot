# Stockpilot

![CI](https://github.com/sakib-101-git/stockpilot/actions/workflows/ci.yml/badge.svg)

An AI-powered inventory and demand platform for small retailers: probabilistic
demand forecasting, budget-constrained reorder recommendations, and an
explainable assistant, built with Python and FastAPI.

**Status:** under construction (Weeks 1-12 done; 13 next).

## What it does

Stockpilot ingests a shop's sales as they happen, forecasts demand per
product 28 days out with calibrated uncertainty, and turns those forecasts
into concrete purchasing decisions: when to reorder, how much, and, when
budget is limited, which products to prioritize. A human stays in the loop
to approve, edit, or reject every suggested order before it's acted on, all
from a working dashboard, with an AI assistant that can answer real
questions about the data by calling the same tested backend directly.
Every part of the pipeline is tenant-isolated, tested against a real
Postgres and Redis, and built to be explainable rather than a black box —
and its value is checked against a simple baseline, not just assumed.

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

**Approval workflow.** The optimizer's suggestions are persisted, not just
returned and forgotten. An owner can approve, edit, or reject each one
(`POST /recommendations/generate`, `GET /recommendations/pending`,
`POST /recommendations/{id}/approve|edit|reject`), with a full audit trail
of who decided what and when. Regenerating recommendations automatically
supersedes stale, still-pending ones from an earlier run rather than
letting them pile up alongside fresh suggestions.

**Policy simulation.** Does the forecast-driven approach actually beat a
simple rule? Fifteen real products, stratified across slow/medium/fast
sellers and all three stores, were replayed through a day-by-day simulated
shop under two policies that differ in exactly one way: what estimates
demand. The forecast-driven policy had 65% fewer stockout-days and 58%
less unmet demand than a 28-day moving-average baseline over the same real
year of sales, winning on 14 of 15 products — the one exception is a
genuine cold-start case with almost no history to learn from. Full
methodology and results in `docs/experiments.md` and
`docs/decisions/0011-policy-simulation.md`.

**Dashboard.** A Streamlit app gives every part of the pipeline a real,
working screen: sign in, see what needs attention, view a product's 28-day
forecast chart with an on-demand explanation of what drove it, and
generate, approve, edit, or reject purchasing recommendations. It's a thin
client with no logic of its own — every page calls the same tested API
endpoints described above — which keeps the door open to a different,
more polished frontend later without touching the backend at all. Details
in `docs/decisions/0012-streamlit-dashboard.md`.

**AI assistant.** A chat page in the dashboard answers real questions
about forecasts, reorder status, and purchasing recommendations by
calling the same tested backend as tools, using Gemini's free tier — it
never guesses a number it can look up. Tenant scoping is enforced by
construction (every tool is bound to one tenant's ID, which the model
never sees or controls), verified with a repeated isolation check rather
than a single pass. Read-only by design: it can explain and recommend but
cannot approve, edit, or reject a real order. An eval suite checks
grounding, hallucination resistance, and tenant isolation across multiple
runs. Details in `docs/decisions/0013-ai-assistant.md`.

**Infrastructure.** Alembic migrations, a test suite that runs against a
real Postgres and Redis rather than mocks, and CI on every push covering
linting, formatting, and the full test suite.

## Quick start

Requires Docker, [uv](https://docs.astral.sh/uv/), and Python 3.12.

```bash
cp .env.example .env
# put a random value in JWT_SECRET_KEY, for example: openssl rand -hex 32
# optionally add GEMINI_API_KEY for the AI assistant (free at
# https://aistudio.google.com/apikey) — everything else works without it
make up        # start Postgres (TimescaleDB) and Redis
make migrate   # apply migrations (also creates the restricted app role)
make run       # start the API on http://localhost:8000
```

Open http://localhost:8000/docs for the interactive API docs.

To run the dashboard (run from the project root, not from inside `dashboard/`):

```bash
uv run streamlit run dashboard/Home.py
```

Open http://localhost:8501 and sign in with an existing account.

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

Assistant tests make real Gemini API calls and are skipped automatically
if `GEMINI_API_KEY` isn't set.

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

To run the policy simulation and compare the forecast-driven reorder
policy against the naive baseline (real historical data, takes roughly
10 minutes since it retrains 13 times across the simulated year):

```bash
uv run python -m scripts.run_simulation
```

To run the assistant's eval suite (measures grounding, hallucination
resistance, and tenant isolation over several real calls; requires
`GEMINI_API_KEY`):

```bash
uv run python -m eval.run_eval
```

## Design decisions

See [`docs/decisions/`](docs/decisions/) for short notes on the main
technical choices and their trade-offs, including where the current data
has known, stated limitations, and
[`docs/experiments.md`](docs/experiments.md) for the full forecasting and
simulation results.
