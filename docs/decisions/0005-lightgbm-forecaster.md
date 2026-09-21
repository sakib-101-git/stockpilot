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
- Known weakness: fold 1421 (Christmas 2014) has RMSSE 0.706 against 0.654 for
  the best baseline, while its pooled RMSE is the best. It forecasts busy
  series well and quiet series badly there. The cause is not established.
- Sales are not demand: stockouts appear as zeros.
- Each series counts equally in RMSSE. M5's official metric weights by revenue.
- The loss weights and their cap are first guesses and were not tuned.