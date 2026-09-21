# 0004: Score forecasts with RMSSE, against per-fold baselines

Status: accepted
Date: 2026-09-22

## Context

About 60% of days in the sample have zero sales, and most series sell less
than one unit a day. Pooled errors let fast sellers dominate. MAE and MASE
are minimised by the median, which is 0 for most series, so they score a
constant forecast of zero almost as well as the best method
(mean MASE 1.019 for zero, 1.037 for the 28-day moving average).
Ordering stock needs the average demand, not the median.

## Decision

- The primary point-forecast metric is RMSSE: squared errors, scaled per
  series by the one-step change in its own history, so every series counts
  equally and the mean level matters. MAE, RMSE, MASE and bias are reported
  as secondary numbers.
- Backtest: rolling origin, horizon 28 days, six folds. Four cover
  February to May 2016 and two cover Christmas in 2014 and 2015. A series is
  scored only if it had at least 56 days of history before the origin.
- The bar for any model is the best baseline in each fold, not the average.

## Results

Baselines tested: zero, naive, seasonal naive, 28-day moving average,
AutoETS, CrostonSBA, TSB. AutoETS and the moving average are effectively
tied (mean RMSSE about 0.71 over six folds). AutoETS wins 4 of 6 folds by
margins under 2%. The intermittent-demand methods lose to the plain
moving average.

## Consequences

- A model must beat roughly 0.65 to 0.74 RMSSE (fold-dependent) to count.
- Sales are not demand: stockouts show as zeros, so all metrics measure
  agreement with sales, not with true demand.
- Every series has equal weight. M5's official metric weights by revenue,
  and we do not.
- Fold scores are not comparable to each other, only methods within a fold.