# 0014: Feature drift detection using Evidently

## Status
Accepted

## Context
The nightly Celery Beat job (Week 8) retrains every tenant's model every
night, unconditionally, with no signal about whether the underlying
demand data has actually changed. Week 13 adds a real drift check ahead
of each retrain — not yet gating whether retraining happens, but making
drift a visible, logged fact rather than invisible.

## Decisions

**Feature-level drift, not raw-sales drift.** The comparison runs on the
same engineered features (`mean_7`, `mean_28`, `mean_56`, `zero_share_28`,
`scale_sq`, `last_day`) that actually feed the model, via
`ml.features.origin_features` — already-validated code from Weeks 6-8,
reused rather than reimplemented. Drift in what the model actually sees
is more directly relevant to its performance than drift in raw daily
units would be.

**Reference data is reconstructed, not stored.** `Forecast` rows do not
record which origin day produced them, only the resulting predictions
and a model version. Rather than add new schema to track exact training
origins (real scope creep this week), the drift check compares a
tenant's engineered features today against the same features computed at
an earlier point in their own history (90 days back, by default) using
identical, already-tested feature code. This answers a closely related,
practically useful question — has this tenant's demand behavior shifted
meaningfully — without claiming to reconstruct the literal training set
a given model version used.

**Two features are deliberately excluded from the comparison, and this
was found by a real, wrong first result, not decided in advance.**
`history_days` and `days_since_sale` are anchored to the origin day
itself: comparing them 90 days apart shows a mechanical shift of roughly
90, every time, for every tenant, regardless of any real change in
demand. The first real run of this feature reported `drift_share=1.0`
(all 8 features "drifted") on ordinary CA_1 data with no known behavior
change — which is what surfaced the bug. Excluding the two time-anchored
features and rerunning against the same data gave a materially different,
plausible result (6 of 6 remaining features drifted, values checked by
hand: `mean_7` +36%, `mean_28` +18%, `mean_56` +15%), consistent with a
real, interpretable seasonal shift (the reference and current windows
span mid-March to mid-June 2016 in the M5 calendar) rather than a
measurement artifact.

**Drift is logged, not yet gating retraining.** The nightly task now
prints a clear drift result (share, which features, significant or not)
for every tenant before regenerating its forecast, but training still
happens unconditionally every night. A "skip retraining when there is no
drift" branch was considered and deliberately not built this week —
it raises real questions (what happens on a tenant's very first run with
no prior reference point, how staleness is tracked over multiple skipped
nights) that deserve a separate, careful step rather than folding in
silently alongside the detection logic itself.

**The nightly task needed the same RLS-ordering fix as nearly every
other week.** The drift check's `load_tenant_history` call has no
tenant-context logic of its own — it expects the caller to have already
set `app.current_tenant` — and the first version of the nightly task's
integration omitted that call before invoking `check_drift`. Caught
before merging, by checking (not assuming) that both service functions
actually set their own context, and confirmed fixed by a real, full
nightly-task run against both live tenants rather than a unit-level
check alone.

## Consequences

**No automated test for the nightly task's drift wiring yet** — only
manual verification, run twice against real CA_1 and TX_1 data (once
that surfaced the missing-context bug, once that confirmed the fix). A
proper test using synthetic data with a known drift/no-drift outcome,
rather than relying on CA_1's real seasonal pattern, is a genuine,
stated gap to close before the week is fully done.

**`DRIFT_SHARE_THRESHOLD = 0.3` (30% of compared features) is a
reasonable-sounding default, not empirically tuned.** With only 6
features being compared, this threshold has coarse granularity (2 of 6
drifting already exceeds it) and has not been validated against multiple
tenants or time windows to check it produces useful, non-noisy alerts in
practice.

**K-S tests on ~150-product samples are statistically sensitive** — a
real, moderate shift (the kind found here) registers clearly, but a
smaller, more marginal shift could also register as "significant" at
this sample size without necessarily being operationally meaningful. The
raw p-values are available per feature if a future need calls for a
stricter or more nuanced threshold than the current binary
significant/not-significant split.
