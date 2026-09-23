# Forecast experiments

Judged on validation folds 1250 and 1700, which are not among the six scoring
folds. Lower RMSSE is better.

| # | Change | 1250 | 1700 | mean |
|---|---|---|---|---|
| 0 | moving average 28d (reference) | 0.661 | 0.697 | 0.679 |
| 1 | LightGBM plain, 14 features | 0.674 | 0.695 | 0.685 |
| 2 | + loss weights of 1 / series scale | 0.664 | 0.688 | 0.676 |
| 3 | + same-weekday mean and ratio (16 features) | 0.663 | 0.688 | 0.675 |
| 4 | settings search: small trees | 0.661 | 0.688 | 0.674 |
| 5 | settings search: tweedie 1.2 | 0.657 | 0.690 | 0.673 |
| 6 | settings search: tweedie 1.5 | 0.655 | 0.691 | 0.673 |
| 7 | settings search: regularised, slower | 0.674 / 0.665 | 0.689 / 0.689 | 0.681 / 0.677 |

Rows 3 to 7 are within noise (about 0.003) of row 2 or worse. Decision: keep
the default settings. A candidate needed a mean gain over 0.003 and no fold
loss over 0.003.


## Final six-fold result

Scoring folds 1421, 1785, 1829, 1857, 1885 and 1913, one fresh model per fold.
Default settings, weighted loss, 16 features.

| method | RMSSE | RMSE | MASE |
|---|---|---|---|
| LightGBM (weighted) | 0.712 | 1.979 | 1.030 |
| AutoETS | 0.709 | 2.040 | 1.006 |
| moving avg 28d | 0.712 | 2.048 | 1.007 |

Process note: choices were judged on validation folds 1250 and 1700. One
exception: the idea of weighting the loss came from diagnosing the first
prototype by category and speed on fold 1913, a scoring fold, so that fold was
not completely untouched.


## Prediction intervals (10% to 90%, validation folds 1250 and 1700)

| method | pinball_mean | coverage | width |
|---|---|---|---|
| empirical 112d | 0.211 | 0.922 | 2.688 |
| LightGBM quantile | 0.213 | 0.885 | 2.635 |
| LightGBM quantile, weighted | 0.217 | 0.890 | 2.566 |

LightGBM does not beat the empirical baseline by the 3% margin set in advance.
Weighted is worse than unweighted, so unweighted stays. Coverage is above the
80% target for all three.


## Interval calibration by speed group (validation folds 1250 and 1700)

Share of outcomes above the upper end (target 0.10, accepted band 0.07 to 0.13,
a guess made before the run):

| method | all | fast | medium | slow |
|---|---|---|---|---|
| LightGBM quantile | 0.100 | 0.107 | 0.118 | 0.075 |
| empirical 112d | 0.070 | 0.089 | 0.072 | 0.050 |

LightGBM's upper end is inside the band in every group. For medium and slow
series the lower end is 0 in every cell, so the 10% to 90% range is effectively
a one-sided upper bound. Pinball_90 still favours the baseline (0.300 against
0.308): calibration on average does not imply better per-series accuracy.


## New-product fallback (validation folds 1250 and 1700, 3 seeds)

About 20% of established series had their history hidden, leaving 7, 14 or 28
days. Peers are other established series of the same store and category.

RMSSE:

| history days | 7 | 14 | 28 |
|---|---|---|---|
| own history mean | 0.730 | 0.715 | 0.713 |
| shrunk to peers, k0=7 | 0.875 | 0.799 | 0.753 |
| LightGBM, unseen series | 0.816 | 0.769 | 0.755 |

Upper 90% bound, share of outcomes above it (target 0.10):

| history days | 7 | 14 | 28 |
|---|---|---|---|
| own history quantile | 0.149 | 0.119 | 0.090 |
| peer shape, k0=7 | 0.074 | 0.080 | 0.086 |

Decision: peer blending does not beat the own-history mean, so it is not used
for point forecasts. For the upper bound, peer shape with k0=7 is better
calibrated below 14 days (and 4% better on pinball at 7 days) but 40% higher.
Own history is better at 28 days. Switch point between 14 and 28 days, set at
21, untested.

Limits: simulated new products are established sellers with hidden history, so
launch effects are absent. Run-to-run noise was not measured.

## Final interval result (six scoring folds)

Rule set before the run: LightGBM counts as better if its mean pinball loss is
lower by more than 3%.

| method | pinball_mean | pinball_10 | pinball_90 | above_upper | width |
|---|---|---|---|---|---|
| LightGBM quantile | 0.209 | 0.121 | 0.298 | 0.096 | 2.800 |
| empirical 112d | 0.219 | 0.122 | 0.317 | 0.078 | 2.705 |

LightGBM is 4.6% lower on average and wins all six folds (2.1% and 1.0% in the
last two). On the validation folds it was about 1% worse, so the ranking
depends on the fold. The gain is all in pinball_90. It is 3.5% wider overall
and 37% wider on slow series. The upper miss rate drifts from 0.088 to 0.107
over the folds; not tested.

New-product rules confirmed on the scoring folds: the own-history mean beats
peer blending at 7, 14 and 28 days (RMSSE 0.749, 0.730, 0.720). Upper bound
miss rate at 7 days: 0.140 own history, 0.068 peer shape. LightGBM on unseen
series moved from 0.816 (validation) to 0.944 at 7 days; not investigated.
## Policy simulation: forecast-driven reorder vs. naive moving average

Rule set before the run: the forecast-driven policy counts as better if it
has meaningfully fewer stockout-days than the naive baseline across the
sample.

Method: 15 real M5 products, 5 each from the slow/medium/fast speed tiers
(`ml.quantiles.speed_groups`), selected by a fixed random seed within each
tier rather than by position, after an initial version of the selection
rule ("lowest index per tier") turned out to be biased toward one store and
one category and was corrected. Both policies use the same reorder
mechanism (lead-time-buffered reorder point, MOQ/pack-size rounding) and
face identical real historical demand for each product; the only
difference is what estimates the reorder point. The forecast-driven policy
retrains a LightGBM point model and a quantile-90 model on the full
~450-series grid every 28 days (13 refreshes across the 365-day window) and
sums the quantile-90 forecast over the lead-time window, using the correct
horizon day of that refresh's 28-day forecast for however long it has been
since the last refresh. The naive policy sums a 28-day trailing moving
average of real sales over the same lead-time window, recomputed every
simulated day. Opening stock for each product is set from its own recent
average daily demand; a product with no real sales in the 28 days before
the simulation window falls back to zero average demand for that
calculation rather than producing a NaN that silently corrupts its whole
simulated run — found and fixed after a first run silently zeroed out one
product's stockout tracking this way.

| policy | total stockout-days | total unmet demand | avg stock |
|---|---|---|---|
| forecast-driven | 129 | 746.0 | 19.9 |
| naive moving average | 368 | 1794.5 | 11.3 |

The forecast-driven policy has 65% fewer stockout-days and 58% less unmet
demand than the naive baseline over the same real year of demand, while
holding roughly 76% more average stock (19.9 vs 11.3) — some of the
improvement is bought with more inventory on hand, not purely better
timing, and this trade-off is not decomposed further here.

The forecast-driven policy wins on 14 of 15 products. The one exception,
`WI_1/FOODS_2_147`, has essentially no real sales in the 28 days before the
simulation window begins — the same product that exposed the NaN bug above
— and the naive policy's simpler, always-available moving average handled
that thin-history case better (19 stockout-days against 34). Consistent
with the cold-start findings elsewhere in this log: a model with too little
recent history to learn from is not guaranteed to beat a simple baseline,
and this simulation did not special-case that condition the way
`ml/coldstart.py` does for point forecasts.

Limits: one run, one 365-day window, one random seed for product selection;
run-to-run variance across seeds was not measured. The naive baseline
updates its estimate every simulated day while the forecast-driven policy's
estimate is frozen between 28-day refreshes — a real asymmetry in the
naive baseline's favor that the result still overcomes. Holding cost is
approximated only as average stock on hand, not priced in actual currency.
