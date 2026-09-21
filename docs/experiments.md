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