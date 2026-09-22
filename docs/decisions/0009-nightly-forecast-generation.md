# 0009: Nightly forecast generation from live event data

## Status
Accepted

## Context
Weeks 5-7 built and validated a LightGBM forecasting pipeline against the
static M5 sample (`sales.parquet`), scored via backtesting (known history,
known future, compare). Week 8 needed to turn that into something the
running application actually produces and serves: real forecasts, from
real accumulated `stock_movements` data, on a schedule, retrievable via
the API, with an explanation of why the model predicted what it did.

## Decisions

**Data source**: forecasts are generated from `stock_movements`, not
`sales.parquet` — the real, RLS-scoped ledger built by Week 4's event
pipeline, not the static file used for backtesting. This required
replaying a much larger slice of M5 (188,014 real sale events, both
seeded tenants) through the actual Redis Streams → consumer pipeline,
rather than seeding a small synthetic sample, so the forecasting task
exercises genuinely accumulated live data end to end.

**Price and zero-sale-day simplifications** (`app/services/forecast_data.py`):
`stock_movements` has no price history, only `Product.current_price` (a
single static value) — every day for a product uses that same price, so
`price_ratio` is uninformative on this path (always ~1.0), unlike the M5
backtest path where real price history drives it. Days with no sale
event, between a product's first and last known sale, are filled as 0
(assumed on-sale, no purchase) rather than left as "unlaunched" — an
assumption, not observed fact; a real stockout or delisting mid-range
would be misread as a zero-sale day.

**True forward forecasting needed new code, not just a new caller.**
`ml.lgbm.forecast()` (Week 6) requires real values past the origin — it
was built for backtesting, where the actual outcome is known and used
both as a feature-safety boundary and as the `y` column to score against.
It cannot produce a forecast for days that have not happened yet: the
target day's true value does not exist, so `build_rows`' filter on
`y.notna()` drops every genuinely-future row. `ml.features.build_forecast_rows`
and `ml.lgbm.forecast_future` were added as siblings — same feature
construction, no `y` requirement, falling back to each series' last known
price for target days beyond the array's width. This is a real
architecture gap Weeks 5-7 did not need to consider, discovered by
attempting the actual forward-forecast case for the first time.

**Row-level security ordering, again.** Every function touching
`stock_movements`, `forecasts`, or any tenant table sets
`app.current_tenant` as its first database operation — including inside
`generate_forecasts_for_tenant`, before the very first `session.get(Tenant, ...)`
call. This is the same lesson from Weeks 3-4, now applied from the start
rather than discovered through a bug, though the nightly-task return-value
plumbing (`run_async` silently discarding the coroutine's result) was a
genuine new bug caught only once the task's return value actually mattered.

**Models are versioned and promoted via MLflow aliases, not stages.**
MLflow 3.16.1 (the installed version) treats the classic "stages" concept
(Staging/Production/Archived) as legacy; the registry API returns
`current_stage='None'` on a freshly registered model and expects aliases
instead. `ml/registry.py` uses `client.set_registered_model_alias(...)`
and loads via `models:/name@champion` — confirmed against the real
installed version in an exploratory notebook session before writing any
code around it, rather than assumed from documentation that may describe
an older API.

**Forecast history is kept, never overwritten.** `forecasts` has no
unique constraint on `(product_id, target_date)` — a nightly rerun
inserts new rows rather than updating existing ones. API endpoints
explicitly query for the most recent `generated_at` per product. This
was exercised for real: CA_1 and TX_1 each have two full forecast runs
(model versions 2/4 and 3/5 respectively) in the database, and the
"latest run only" logic is covered by both a manual verification against
real multi-run data and an automated test.

**Per-forecast explanations are computed on demand, not pre-stored.**
SHAP (`TreeExplainer`) runs against the freshly-loaded champion model and
a rebuilt feature row, per request — roughly 2-3 seconds on real data,
dominated by rebuilding a tenant's full history grid from
`stock_movements` rather than the SHAP computation itself (which is fast
on a single row). Not optimized in Week 8's scope; acceptable for a
deliberate "explain this forecast" interaction, not suitable for a list
endpoint.

**A real data bug found and corrected**: the replay script wrote
timestamps without an explicit timezone; the consumer's
`datetime.fromisoformat(...)` produced naive datetimes that, when written
to a `timestamptz` column, picked up the process's local timezone
(`Asia/Dhaka`, +6) rather than the intended UTC — silently shifting every
`occurred_at` back 6 hours (a date landing on the wrong calendar day for
every single row). Fixed in code (explicit `.replace(tzinfo=UTC)`) and
corrected retroactively across all 188,014 existing rows via a verified,
uniform `+ INTERVAL '6 hours'` update once the shift was confirmed
mechanically, not assumed.

## Consequences

- Forecasts cannot extend past `2016-06-19` — the real M5 calendar data's
  last date. A tenant whose real history reaches that boundary cannot get
  a 28-day-ahead forecast without a newer calendar source. Not an issue
  for the current replayed dataset, but a real ceiling worth knowing.
- A tenant needs at least `max(min_history, first_origin) + horizon` days
  of real history (105+ days by default) before the nightly task can
  forecast for it at all — a newly registered tenant with little history
  will fail this check and be skipped (logged, not silently ignored) by
  the nightly run's per-tenant error handling.
- The explanation endpoint's ~2.5s latency is a known, accepted
  limitation for this week's scope, not a solved problem.
- Every price signal in the live-data forecasting path is a
  simplification (constant, not historical) — a real limitation worth
  stating plainly rather than implying the live-data forecasts are as
  price-aware as the M5-backtested ones from Weeks 5-7.
