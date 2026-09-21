# Forecast experiments

Judged on validation folds 1250 and 1700, which are not among the six scoring
folds. Lower RMSSE is better.

| # | Change | 1250 | 1700 | mean |
|---|---|---|---|---|
| 0 | moving average 28d (reference) | 0.661 | 0.697 | 0.679 |
| 1 | LightGBM plain, 14 features | 0.674 | 0.695 | 0.685 |
| 2 | + loss weights of 1 / series scale | 0.664 | 0.688 | 0.676 |