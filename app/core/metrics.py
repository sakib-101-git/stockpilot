"""Prometheus metrics beyond the generic HTTP ones (handled by
prometheus-fastapi-instrumentator). Uses tenant_id, not tenant_name, as a
label — an opaque identifier is more defensible in an observability
system than a human-readable business name, even for a demo project.
"""

from prometheus_client import Counter, Histogram

# Buckets sized from real observed durations (~41-44s per tenant on the
# current dataset), not the client library's web-request-oriented
# defaults (0.005-10.0s) — the first real run put every observation in
# the +Inf bucket, which is technically correct but useless for seeing
# the actual distribution.
forecast_generation_seconds = Histogram(
    "stockpilot_forecast_generation_seconds",
    "Time to generate forecasts for one tenant",
    labelnames=["tenant_id", "outcome"],
    buckets=(5.0, 15.0, 30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 300.0),
)

drift_share = Histogram(
    "stockpilot_drift_share",
    "Share of features flagged as drifted per drift check",
    labelnames=["tenant_id"],
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

optimizer_solve_seconds = Histogram(
    "stockpilot_optimizer_solve_seconds",
    "Time for the budget optimizer to solve",
    labelnames=["tenant_id"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)

celery_task_total = Counter(
    "stockpilot_celery_task_total",
    "Celery task completions",
    labelnames=["task_name", "outcome"],
)
