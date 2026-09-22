# 0007: Synthetic supplier, cost, lead-time and stock data

## Status
Accepted

## Context
M5 has no suppliers, unit costs, lead times, opening stock, or shelf-life
data — only sales, prices, and calendar/event information. Stockpilot's
reorder logic (Week 9) needs all of these per product. Since none of it
exists in the source data, it must be generated.

## Decision
Generate plausible synthetic values, seeded for reproducibility
(`scripts/synth/generate.py`, `SEED = 42`), rather than leaving these
fields empty or hand-entering them:

- **Suppliers**: 2-3 per tenant, randomly assigned to products within
  that tenant.
- **Unit cost**: 60% of the product's historical average `sell_price`
  from M5 (`COST_MARGIN = 0.60`) — a simplifying assumption about retail
  margin, not derived from any real cost data.
- **Lead time**: mean drawn from a category-based range (FOODS 3-7 days,
  HOUSEHOLD/HOBBIES 5-10 days), std as 20% of the mean.
- **MOQ / pack size**: drawn from a small fixed set of plausible values
  (1, 6, 12, 24).
- **Opening stock**: 2-4 weeks of the product's historical average daily
  sales, as a single `StockMovement` receipt dated at a fixed origin day
  (day 1913, matching the last backtest fold's origin).
- **Batches**: created only for FOODS products (the only category where
  shelf life is meaningful), one batch matching the opening-stock
  quantity, with a random shelf life of 7-60 days from the same origin
  date.

Generation logic (`scripts/synth/generate.py`) is pure and fully unit
tested with no I/O. Writing to the database is a separate, thin script
(`scripts/synth/seed.py`), run manually and idempotently per tenant
(skips a tenant that already has supplier rows).

Product catalogs themselves are loaded separately
(`scripts/synth/load_products.py`), before this script runs, since
`seed.py` only creates supplier/cost/stock data for products that
already exist.

## Consequences

**Every number here is invented, not observed**, and this must stay
visible to anyone using the data — flagged in the module's own
docstring and in the README.

**Costs, MOQ and pack sizes are not derived from anything real** — no
real retail margin data, no real supplier catalog constraints. Lead
times are a category-level guess, not per-supplier or per-route data.

**Row-level security ordering matters for any script that writes
tenant-scoped tables.** Both `seed.py` and `load_products.py` must call
`SELECT set_config('app.current_tenant', ...)` as the *very first*
database operation in a tenant's scope — including before the read that
checks "has this tenant already been seeded". Getting this wrong doesn't
raise an error: it makes every query on that connection silently return
zero rows, which looks exactly like "nothing to do" rather than a
failure. This was found the hard way during this week's work (a
partially-seeded tenant, from an earlier attempt before the ordering fix,
looked identical to "already fully seeded" until row counts were checked
by hand) — see the comment left in `_seed_tenant` in `seed.py`.

**Timestamp columns need explicit type conversion when writing plain
`date` objects into `DateTime(timezone=True)` columns** — `StockMovement`
hit this (`plan_opening_stock` produces a `date`, but `occurred_at` is a
timezone-aware `datetime` column); `Batch`'s `received_at`/`expires_at`
are plain `Date` columns and don't have this issue.

**No real per-supplier variation.** All suppliers for a tenant draw from
the same lead-time and cost logic — a real supplier catalog would have
meaningfully different suppliers offering different terms for the same
product, which this data does not model.

## Alternatives considered
Leaving these fields nullable and unpopulated until real data exists —
rejected because the ordering, forecasting-to-decision pipeline (Week 9)
needs *something* to compute against to be demonstrable, and clearly
synthetic-but-plausible data serves that better than empty tables or
hand-typed one-off values.