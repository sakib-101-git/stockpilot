# 0011: Policy simulation comparing forecast-driven reorder against a naive baseline

## Status
Accepted

## Context
Weeks 8-9 built forecasting and a reorder optimizer, but nothing yet
demonstrated that the forecast-driven approach actually produces better
purchasing decisions than a simple rule a small shop might already use.
Week 10 builds that comparison directly: replay real historical demand
through a simulated shop under two different reorder policies and measure
the difference.

## Decisions

**Data source is the M5 sample grid (`sales.parquet`), not
`stock_movements`.** The real CA_1/TX_1 stock data has a known, documented
limitation (Week 9's decision note): no simulated replenishment, so
current stock is deeply negative and unrepresentative of a real shop. The
simulation needed clean, real demand data with a working replenishment
model built around it, which the M5 grid provides directly.

**The comparison isolates one variable: what estimates demand.** Both
policies share the same reorder mechanism (lead-time-buffered reorder
point, MOQ/pack-size rounding) and face identical real historical demand
each simulated day. The forecast-driven policy sums a LightGBM quantile-90
forecast over the lead-time window; the naive baseline sums a 28-day
trailing moving average over the same window. Everything else held
constant, so any difference in outcome is attributable to the forecasting
method, not to an unrelated policy difference.

**Products are sampled by a fixed random seed within each speed tier, not
by position.** An initial version selected the lowest-index series per
tier, which turned out to select only `CA_1` and only `FOODS` products —
an artifact of how the underlying grid happens to be ordered, not a
representative sample. Fixed-seed random selection within each tier
(`slow`/`medium`/`fast`, from `ml.quantiles.speed_groups`) fixed this: the
final sample spans all three stores and five category groups.

**Supplier terms reuse Week 3's synthetic generation logic directly, not
new constants**, applied to the 15 sampled products. A real bug surfaced
here: `sku` is only unique within a store, so two sampled products with
the same sku in different stores collided when keyed by sku alone.
Fixed by pairing supplier-plan output with its source rows positionally
instead of re-keying by sku.

**The forecast-driven policy retrains every 28 days, not daily.** Global
LightGBM models cover all ~450 series per training run, so the cost
driver is the number of retrains across the 365-day window, not the
number of sampled products. 13 refreshes (roughly monthly) is a
realistic cadence for a small business and keeps total runtime to about
10 minutes. Between refreshes, a product's reorder point uses the
correct horizon day of that refresh's frozen 28-day forecast (day d since
refresh reads forecast day d), not always day 1 — this costs nothing
extra since the full 28-day forecast is already computed at each refresh.

**A known, stated asymmetry**: the naive baseline recomputes its moving
average every single simulated day, while the forecast-driven policy's
estimate is frozen between 28-day refreshes. This is inherent to comparing
a cheap heuristic against an expensive model with a realistic retrain
cadence, and it works in the naive baseline's favor, not the
forecast-driven policy's — the result below holds despite this, not
because of an unfair setup in the forecast policy's favor.

## Result (see `docs/experiments.md` for the full write-up)

Forecast-driven: 129 total stockout-days, 746.0 total unmet demand, across
15 real products over the most recent 365 days. Naive baseline: 368
stockout-days, 1794.5 unmet demand. A 65% reduction in stockout-days and
58% reduction in unmet demand, at roughly 76% higher average stock held
(19.9 vs 11.3) — part of the improvement is bought with more inventory on
hand, not purely better timing.

The forecast-driven policy wins on 14 of 15 products. The one exception has
almost no real sales in the 28 days before the simulation window and is a
genuine cold-start case: the naive baseline's simpler, always-available
estimate beat the model that had too little recent history to learn from.
This is consistent with, not contradictory to, the cold-start findings
already recorded elsewhere in `docs/experiments.md`.

## Consequences

**A real bug was found and fixed via this simulation, not before it**: a
product with no real sales in the pre-simulation window produced a NaN
initial stock value, which — because of how Python's `min()` handles NaN
comparisons — silently made that product's stockout detection always
report zero, under both policies, for the entire run. Caught by comparing
`avg_stock: nan` in a first run's output against expectation, not by
inspection beforehand. Fixed with an explicit all-NaN check and a
zero-demand fallback.

**Not decomposed further**: the higher average stock under the
forecast-driven policy is not broken into a proper holding-cost figure in
currency terms, and the improvement is not validated across multiple
random seeds or simulation windows — this is one run, honestly reported
as such, not a claim of statistical significance.
