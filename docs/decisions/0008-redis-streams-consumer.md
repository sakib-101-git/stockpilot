# 0008: Redis Streams sales event pipeline

## Status
Accepted

## Context
Stockpilot needs a live-updating stock ledger. Note 0002 (Week 1) already
chose Redis Streams over Kafka for this, on the grounds that Redis is
already in the stack and the project's scale doesn't need Kafka's
distributed guarantees. This note covers the actual implementation and
what was learned building it.

There is no real point-of-sale integration to source events from, so the
producer side replays M5's historical sales as if they were live —
clearly stated as simulated, not real-time, data.

## Decision

**Producer** (`scripts/synth/replay.py`): reads the prepared M5 sample,
filters to rows with `units > 0` (a zero-sale row is not a transaction),
and pushes one event per sale onto a single `sales-events` stream, in
date order. Each event carries a self-generated `event_id` (UUID),
separate from Redis's own auto-generated stream entry ID — this is the
field used for idempotency, since a manual re-run of the replay script
produces new stream IDs for logically identical historical sales, and
relying on Redis's ID for deduplication would not survive that.

**Consumer** (`workers/stream_consumer.py`), one Redis consumer group
(`stock-consumers`) reading the stream:
- Each event becomes one `StockMovement` row (`movement_type=SALE`,
  negative quantity).
- Idempotent on `event_id`, stored in `StockMovement.reference` as
  `event:<uuid>`, checked before insert. This is a check-then-insert, not
  a database constraint — safe under one sequential consumer, not
  provably safe under true concurrent consumers processing the same
  event simultaneously. Acceptable at this project's scale; flagged as a
  known limitation.
- Failed events are retried using Redis's own per-entry delivery count
  (`XPENDING`'s `times_delivered`), up to `MAX_DELIVERIES = 3`. Orphaned
  entries (from a crashed or slow consumer) are reclaimed via
  `XAUTOCLAIM` at the start of every loop iteration, so a restart resumes
  unfinished work rather than leaving it stuck.
- An event that exhausts its retries is copied, with all original fields
  plus a `failure_reason`, to a separate `sales-events-dead` stream, and
  acked off the main stream — so a permanently bad event cannot block
  processing indefinitely, while still being inspectable afterward.

**Row-level security**: `app.current_tenant` must be set before the
*first* query touching any tenant-scoped table, including read-only
checks like "does this event already exist" — not just before writes.
This was the single most repeated bug this week (also hit in Week 3's
CSV import and seed script): getting the ordering wrong does not raise
an error, it makes the query silently return zero/no rows, which looks
exactly like "nothing to do" rather than a failure. Every function in
this pipeline that touches the database sets the tenant context as its
first database operation.

## Consequences

**This is simulated live data, not a real integration.** The replay
script exists purely to demonstrate the pipeline against real historical
patterns; a production system would replace it with an actual POS
webhook or polling integration, with the consumer side unchanged.

**Idempotency is check-then-insert, not constraint-enforced.** A unique
database constraint on `(tenant_id, event_id)` was considered and
rejected because `StockMovement.reference` is already used with
deliberately non-unique values elsewhere (`seed.py`'s opening-stock rows
all share one reference string per tenant); a blanket constraint would
break that. Under single-consumer sequential processing (what's built),
this is correct. It is not proven correct under multiple concurrent
consumers racing on the same event — not needed at current scale, but
worth revisiting if the worker is ever scaled horizontally.

**Dead-lettered events require manual inspection.** There is no
automated alerting or retry-from-dead-letter mechanism; an operator
would need to query the `sales-events-dead` stream directly. Acceptable
for this project's scope.

**`WI_1` (the third M5 store/tenant) was never seeded** with products or
supplier data in Week 3, so a full, unfiltered replay of all 450 series
will report roughly a third of events as skipped (no matching
tenant/product) — not a bug, just a consequence of only two of three
sample tenants existing so far.