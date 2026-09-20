# 0002: Redis Streams instead of Kafka for the event pipeline

Status: accepted (to be checked against load-test results in Week 14)
Date: 2026-09-21

## Context

Sales events arrive through an API (or a replay script) and must be stored
reliably without slowing the API down. So the API puts each event on a queue
and separate workers process it. The workers must be able to retry failures,
avoid processing the same event twice, and set aside events that keep failing.

Redis is already in the stack (Celery broker and cache).

Expected scale: the replay dataset is about 690,000 events. A load test may
push a few thousand events per second, but this is a single-machine project.

## Decision

Use Redis Streams with consumer groups. Workers acknowledge each event after
processing it. Events that fail repeatedly go to a dead-letter stream.

Not chosen: Kafka.

## Consequences

Good:
- No new infrastructure. Redis is already running, so there is one less system
  to deploy, monitor and explain.
- Consumer groups, acknowledgements and retries cover what we need.
- Simple to run locally and in CI.

Costs:
- Events live in memory. The stream must be trimmed to a maximum length, and it
  cannot act as a permanent history. The permanent record is the database.
- Persistence is weaker: a Redis crash can lose the most recent events,
  depending on how it is configured. Kafka replicates data across servers.
- It does not scale out across many machines the way Kafka's partitions do.

## When this decision should change

Move to Kafka if event volume grows past what one Redis instance can handle,
if events must be kept and replayed for long periods, or if several separate
systems need to read the same stream independently.

