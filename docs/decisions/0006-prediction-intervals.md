# 0006: Prediction intervals from quantile LightGBM

Status: accepted
Date: <today's date>

## Context

A shop needs a range around each forecast, because the gap between the forecast
and a high outcome sets its safety stock. About 60% of days are zero and sales
are whole numbers, so the lower end of a 10% to 90% range is usually 0.

## Decision

- Two LightGBM models (10% and 90%) with pinball loss, on the same features and
  training table as the point model. One fresh pair per fold, trained only on
  targets up to that fold's origin. Forecasts are sorted so the lower end never
  exceeds the upper end (the models never crossed in the backtests).
- Baseline: each series' own empirical quantiles over 112 days.
- The range is effectively a one-sided upper bound. For medium and slow series
  the lower end was 0 in every cell, so the product is described as the "90th
  percentile forecast", not an 80% interval.
- New products (under about 56 days of history): the point forecast is the
  series' own average. The upper bound uses the shape of established peers (same
  store and category) scaled by the product's level (blend constant k0=7) below
  21 days of history, then the product's own 90% quantile. The 21-day switch is
  a midpoint between 14 and 28 days and was not tested.

## Results

Six scoring folds: pinball_mean 0.209 for LightGBM against 0.219 for the
baseline (4.6% lower, winning all six folds). All of the gain is at the upper
end (pinball_90 0.298 against 0.317). Upper miss rate 0.096 (target 0.10),
inside the accepted band 0.07 to 0.13 in every speed group. On the validation
folds LightGBM was about 1% worse, so the margin is fold-dependent.

## Consequences

- The upper bound is 37% wider than the baseline on slow series, so it asks
  for more buffer stock on slow items. The cost shows up in Week 9.
- The upper miss rate drifted from 0.088 to 0.107 over the six folds. Not tested
  whether that is a trend.
- Simulated new products are established sellers with hidden history, so launch
  effects (promotions, a first-weeks ramp) are absent. Peers are the same store
  and category only. Run-to-run noise was not measured. LightGBM on unseen series
  was unstable (RMSSE 0.816 on validation, 0.944 on the scoring folds).
- Sales are not demand: a stockout appears as a zero.