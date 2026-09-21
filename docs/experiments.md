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