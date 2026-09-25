# 0015: Structured logging, Prometheus metrics, and a Grafana dashboard

## Status
Accepted

## Context
Every part of the system built through Week 13 worked, but nothing was
observable in the way a real deployed system needs to be: logs were
plain print() statements, there were no metrics, and nothing had ever
actually been verified to run correctly as the containers it would
eventually be deployed as. Week 14 built structured logging, Prometheus
metrics with a Grafana dashboard, and — because building the dashboard
forced testing the real Docker images end to end for the first time —
surfaced and fixed four genuine, previously invisible production bugs.

## Decisions

**Structured JSON logging via stdlib `logging`, not a new dependency.**
A custom `JSONFormatter` plus a `contextvars`-based request ID, rather
than adding `structlog` or similar — simple enough to build directly
given how many purpose-built libraries this project already integrates.
A `ContextVar` (not a plain global) is required for correctness here,
since a plain variable would leak request IDs across concurrent async
requests.

**A real gap found immediately**: `configure_logging()` was originally
only called in `app/main.py`, so every Celery task's log calls silently
fell back to Python's unconfigured default handler — plain text, no
JSON, no request context — until `workers/celery_app.py` was found to be
missing the same call and fixed to set it up for every worker process.

**Prometheus via `prometheus-fastapi-instrumentator` for HTTP metrics,
plus three hand-picked business metrics**: `forecast_generation_seconds`,
`drift_share`, and `optimizer_solve_seconds`, tied directly to this
project's own domain rather than only generic request counts. Labels use
`tenant_id`, not `tenant_name` — an opaque identifier is more defensible
in an observability system than a human-readable business name, even for
a demo project.

**Histogram buckets were wrong on the first attempt, found by looking at
real data rather than trusting the library's defaults.** The default
buckets (`0.005` to `10.0` seconds) are sized for web-request latencies;
real forecast generation takes 40-50+ seconds, so every observation
landed in the catch-all `+Inf` bucket — technically correct, useless for
seeing an actual distribution. Buckets for both `forecast_generation_seconds`
and `optimizer_solve_seconds` were rebuilt from real measured durations
instead of assumed defaults.

## Four real Docker bugs found while building the dashboard

None of these were introduced this week — each had been latent since
the week that added the code path in question, invisible because the
containers had apparently never been exercised end to end before.

**1. The API image was missing `ml/` and the `ml` dependency group.**
`app/api/forecasts.py` imports `ml.explain` for the SHAP endpoint (Week
8), but `docker/api.Dockerfile` never copied `ml/` and explicitly
excluded the `ml` dependency group (`--no-group ml`), a decision from
Week 3 made before that endpoint existed. The container crashed on
`uvicorn` startup with `ModuleNotFoundError`, every time, since Week 8 —
only surfaced now because this was the first time the API container was
actually started via Docker Compose rather than run locally via `make
run` (which uses the full local `.venv` and never hit this gap).

**2. The worker image was missing `libgomp1`.** LightGBM's compiled core
needs GNU OpenMP's runtime library, which `python:3.12-slim` does not
ship. The worker crashed at Celery startup itself
(`OSError: libgomp.so.1: cannot open shared object file`) the moment it
tried to import `ml.lgbm`, meaning the worker container could never
successfully boot at all. Fixed with `apt-get install libgomp1`.

**3. The worker image was missing `data/processed/`.** `.dockerignore`
excluded all of `data/` (added in Week 1, before nightly forecasting
existed), so `calendar.parquet` — needed by `align_calendar` for every
real forecast run — was never in the build context. Narrowed the
exclusion to `data/raw/` only, keeping the large, runtime-unneeded M5
source CSVs out while including the small processed files the worker
genuinely needs.

**4. Celery's prefork pool silently split the metrics registry.**
`start_http_server(9101)` ran once in the parent process before Celery
forked twelve child worker processes; each fork gets its own copy of
process memory, including a separate copy of `prometheus_client`'s
registry. Tasks executed in a forked child recorded observations into
that child's private registry copy — never visible to the HTTP server,
still running in the parent, serving the parent's own copy. The fix used
here is `--pool=solo` (single process, no forking), a deliberate,
documented trade-off appropriate at this project's scale (a lightweight,
already-sequential nightly job) rather than the heavier
`PROMETHEUS_MULTIPROC_DIR` multi-process aggregation mechanism a
higher-concurrency deployment would need instead.

**A related, smaller fix**: `start_http_server(9101)` originally ran
unconditionally at module import time, so any script that merely
imports `workers.celery_app` to dispatch a task via `.delay()` — not
just the real worker process — also tried to bind port 9101, failing
with "Address already in use" against either the real worker container
or a second competing script. Gated behind a `STOCKPILOT_WORKER_PROCESS`
environment variable, set only in the worker Dockerfile, so only the one
real worker process ever starts the metrics server.

**A debugging detour worth naming plainly**: several `docker compose
exec api curl ...` checks appeared to show missing metrics, prompting a
long chase through registry-mismatch and stale-build theories before
discovering `curl` is not installed in the `python:3.12-slim` image at
all — every one of those checks had silently failed at the `exec` step,
producing empty output that looked exactly like "no metrics" but meant
nothing at all. The registry and rebuild theories were reasonable given
the (invalid) evidence, but the lesson holds regardless: verify the
diagnostic tool itself works before trusting what it reports.

## Consequences

**The dashboard is genuinely correct now, not just plausible-looking.**
Every panel was checked against real, independently-verified numbers
(drift share matching Week 13's hand-verified 1.0, forecast durations
matching structured log output) before being trusted.

**This is the first time both Docker images have been proven to boot
and run correctly, end to end, via Docker Compose** — a meaningfully
different and stronger guarantee than "the test suite passes," since the
test suite runs against source code directly and never previously caught
any of these four gaps.

**A new CI job (`docker-smoke-test`) builds the API image and checks
`/health` on every push**, specifically to catch bug #1's class of
failure automatically going forward. It does not yet cover the worker
image (bugs #2-#4) — a real, stated gap, since a meaningful worker smoke
test needs a running Postgres/Redis and enough real data to attempt a
task, a heavier CI job than the API's stateless health check and
deliberately left for a later, more deliberate addition rather than
rushed in here.

**Not yet done**: the Locust load test (the other half of Week 14's
original scope), and wiring the still-unused `celery_task_total` counter
that exists in `app/core/metrics.py` but has never actually been
recorded anywhere.

## Load test results (Locust, 10 concurrent users, 60s)

A weighted mix reflecting real usage — mostly reading forecasts and
pending recommendations, occasionally running the budget optimizer —
against the real, fully-fixed Docker Compose stack.

| endpoint | requests | failures | median | p95 | p99 | max |
|---|---|---|---|---|---|---|
| `/auth/login` | 10 | 0 | 430ms | 690ms | 690ms | 690ms |
| `/forecasts/summary` | 133 | 0 | 34ms | 300ms | 490ms | 1405ms |
| `/recommendations/pending` | 117 | 0 | 7ms | 250ms | 340ms | 348ms |
| `/optimize-budget` | 21 | 0 | 1000ms | 2900ms | 3500ms | 3512ms |

Zero failures across 281 requests on every endpoint — the system held up
correctly under concurrent load, including RLS and connection pooling,
which were never previously exercised with genuine concurrency.

`/optimize-budget` is the clear outlier: a median of 1 second and a p99
above 3.5 seconds, an order of magnitude slower than the read endpoints,
and visibly climbing as concurrent requests accumulated during the run.
This is a real, honest finding, not glossed over: the OR-Tools solve
itself was independently measured earlier the same day at 8-480ms in
isolation, so the gap under load points to something else — most likely
contention in `_candidate_orders`' database query or the connection pool
— as the actual bottleneck under concurrency, not the solver. Not
root-caused further here; a reasonable next step would be to profile
`_candidate_orders` specifically under concurrent load rather than
assume the solver is at fault just because it is the most
computationally distinctive part of the endpoint.
