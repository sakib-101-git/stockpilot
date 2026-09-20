# 0001: Use the M5 (Walmart) dataset

Status: accepted
Date: 2026-09-20

## Context

Stockpilot needs realistic retail sales history to train and evaluate
forecasting models. Real shop data is not available yet.

M5 has about 30,000 product-store series over 1,941 days, with weekly prices,
holidays and SNAP (US food-benefit) days. Using all of it would produce about
59 million rows, which is too slow to iterate on.

## Decision

Use M5, cut to a sample built by `scripts/prepare_m5.py`:

- 3 stores (CA_1, TX_1, WI_1). Each store acts as one tenant.
- 50 items from each of FOODS, HOUSEHOLD and HOBBIES (stratified sample,
  fixed seed 42), so slow and fast sellers are both represented.
- 450 series, 689,343 rows after cleaning.

Rows before an item's first listed price were dropped (184,107 rows). No units
were ever sold on those rows, and a missing price means the item was not yet on
sale, so they are not real zero-demand days. Keeping them would flatter
accuracy metrics, because predicting zero for a product that does not exist is
always correct.

## Consequences

Good:
- Real demand patterns: intermittent demand (60.2% of days have zero sales),
  price effects and event effects.
- Small enough to experiment quickly, and reproducible from one script.

Costs:
- M5 has no suppliers, unit costs, lead times, stock levels or shelf life.
  These will be generated synthetically and documented as assumptions.
- Sales are not demand: when an item is out of stock, sales read zero even
  though customers wanted it. M5 cannot fix this. It is a known limitation.
- It is US retail data, not South Asian shops. The README will say so.