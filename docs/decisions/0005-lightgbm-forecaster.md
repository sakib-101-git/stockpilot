# 0005: LightGBM as the point forecaster

Status: accepted
Date: 2026-09-22

## Context

The statistical baselines (28-day moving average, AutoETS) are effectively
tied (mean RMSSE 0.712 and 0.709). The plan needs one framework that also
gives prediction intervals (Week 7) and per-forecast explanations (Week 8).

## Decision

One global LightGBM model for all series and all 28 horizons.

- One row per series, origin day and horizon. Origins every 7 days from day
  100, about 2.6 million rows at cutoff 1913.
- 16 features: level features at the origin (last day, 7, 28 and 56-day means,
  zero share, days since last sale, history length), the horizon, target-day
  facts (weekday, month, event type, SNAP, price, price ratio) and a
  same-weekday mean and ratio.
- Loss: squared error, with each row weighted by 1 / its series' one-step
  squared scale, capped at the 99th percentile. This mirrors RMSSE. The plain
  model was worse on slow series (0.694 against 0.665 for the moving
  average) because busy series dominated the raw squared error.
- One fresh model per backtest fold, trained only on targets up to that fold's
  origin.

## Leakage controls

- Training arrays are cut at the cutoff before any row is built.
- Tests overwrite every value after the cutoff with 1e9 and require identical
  features and forecasts.
- Assumption: the target-day price is known in advance (shops set prices
  ahead). Not tested.

## Results

Six-fold means, RMSSE (primary): LightGBM 0.712, AutoETS 0.709, moving average
0.712. Pooled RMSE: 1.979 against 2.040 and 2.048, lower in all six folds.
MASE: 1.030 against 1.006 and 1.007.

Weekday features and a settings search (small trees, regularisation, Tweedie
loss) gave nothing beyond noise (about 0.003) on the validation folds, so
defaults stay.

## Consequences

- LightGBM does not beat the best baseline on the primary metric. It is chosen
  because it matches it, wins on volume-weighted error, and supports quantile
  models and feature attributions. The baselines stay as references and as
  fallbacks.
- Known weakness: on the slowest third of series the model loses clearly in
  fold 1421 (RMSSE 0.724 against 0.527 for the moving average). On the
  busiest third it wins (0.712 against 0.754) and on the middle third it ties.
  Christmas Day itself was forecast better than the baseline (RMSE 1.16
  against 2.57): the average across series was zero that day, LightGBM
  predicted 0.47 and the moving average 1.2. Why slow series lose is not yet
  established.
    Not caused by Christmas Day (the gap is the same without it). LightGBM
  over-forecasts the slow group by 23% (0.179 against 0.145 actual) but the
  moving average under-forecasts it by 31% and still wins, so group-level bias
  is not the explanation. Untested guess: LightGBM's forecasts for individual
  quiet series vary more than a plain average.
- Sales are not demand: stockouts appear as zeros.
- Each series counts equally in RMSSE. M5's official metric weights by revenue.
- The loss weights and their cap are first guesses and were not tuned.