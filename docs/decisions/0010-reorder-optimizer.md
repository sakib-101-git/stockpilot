# 0010: Reorder point and budget-constrained order optimizer

## Status
Accepted

## Context
Week 8 produces forecasts (point estimate and a calibrated 90th-percentile
upper bound) per product per day. Week 9 turns those into purchasing
decisions: how much stock should be on hand, when to reorder, how much to
order, and, when purchasing budget is limited, which products to reorder
first.

## Decisions

**Reorder point is built directly on the Week 7 upper-bound forecast, not
a re-derived classical safety-stock formula.** The standard inventory-
theory approach (z * sigma_demand-during-lead-time, combining demand and
lead-time variance under a normality assumption) would require backing
out an implied standard deviation from the point/upper-bound gap and
introducing a fresh distributional assumption on top of it. Since Week 7
already validated the upper bound's real coverage rate against six
backtest folds (9.6% of outcomes exceeded it, against a 10% target), using
it directly is more defensible than re-deriving and assuming normality a
second time. reorder_point is the sum of the upper-bound forecast across
a lead-time window.

**The lead-time window is ceil(lead_time_days_mean + lead_time_days_std)**,
one standard deviation of buffer on delivery timing, not just demand. A
supplier with more erratic delivery times gets a longer coverage window,
using data (ProductSupplier.lead_time_days_std, from Week 3's synthetic
supply data) that existed but was unused until now.

**A lead time exceeding the 28-day forecast horizon raises an error rather
than silently under-counting.** Summing only the days available and
returning a falsely small reorder point would be a worse failure mode for
an actual purchasing decision than a visible, explicit error.

**Order quantity rounds up to pack size, then up to MOQ if still below it,**
using max(ceil(raw_need / pack_size) * pack_size, moq). Both values are
read from Week 3's ProductSupplier.

**The budget-constrained optimizer is framed as 0/1 knapsack, not
continuous allocation.** Partially covering a product's reorder gap does
not meaningfully reduce its stockout risk during the lead-time window;
either the buffer is covered or it isn't, so each product is a binary
"fully reorder or skip" decision, not a fractional one. Solved with
OR-Tools' CP-SAT solver: candidate products (cost, priority) as boolean
variables, total cost constrained to the budget, priority sum maximized.

**Priority is the fraction of the reorder point currently uncovered**
(raw_need / reorder_point, clamped to [0, 1]), not the raw unit
shortfall. This keeps the optimizer scale-free. A low-volume product
that is 100% short of its (small) buffer is exactly as urgent as a
high-volume product 100% short of its (large) buffer, rather than the
optimizer systematically favoring high-volume products by raw numbers.

**OR-Tools is a core dependency, not in the ml group.** Unlike
lightgbm/scikit-learn/statsforecast, it does not pull in the heavy
numpy/pandas/ML stack, and the optimizer endpoint needs to answer
synchronously inside an HTTP request (confirmed at roughly 1.4 seconds
against real CA_1 data with 150 candidate products) rather than run as a
background task.

## Consequences

**A real, known data limitation surfaced by testing against real data,
not synthetic fixtures.** CA_1's actual current_stock (summed from
stock_movements) is deeply negative (around -13,600 units for the product
checked), because Week 3's seed script created one opening-stock receipt
and the subsequent 188K-event replay then subtracted five years of real
sales on top of it with no simulated replenishment in between. The
reorder and optimizer logic are both confirmed correct against this data
(the arithmetic checks out by hand), but the demo dataset's stock numbers
do not reflect a plausible real shop. A production deployment would have
continuous receipt events and never accumulate this deficit. Documented
rather than silently patched around; fixing it would mean re-engineering
Week 3-4's seed/replay process, outside Week 9's scope. Formal tests use
realistic synthetic fixtures (positive stock, varied priorities)
specifically to avoid baking this anomaly into the test suite, and to
prove the priority-discrimination behavior that saturated real data
(every product at priority 1.0) cannot demonstrate.

**The optimizer recomputes get_reorder_recommendation once per candidate
product** (2-3 queries each) rather than a single batch query, which is
straightforward but means the per-request cost scales linearly with
catalog size. Fine at roughly 150 products (confirmed about 1.4s); would
need revisiting at meaningfully larger scale.

**No persistence of optimizer decisions yet.** optimize_budget returns a
result but does not record it. Week 10's approval workflow is where "you
were shown this recommendation and approved/edited/rejected it" becomes
a stored, auditable decision.
