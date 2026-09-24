# 0013: AI assistant with tool-calling, backed by Gemini's free tier

## Status
Accepted

## Context
Weeks 1-11 built a complete, tested system: forecasting, an optimizer, an
approval workflow, and a dashboard. None of it could answer a plain-
language question. Week 12 built an assistant that calls the existing,
tested backend as tools, so its answers come from real data, not the
model's own guesses.

## Decisions

**Gemini's free tier (`gemini-3.5-flash-lite`), not a paid API.** A
genuine cost constraint, not a compromise made silently: this model
supports real function/tool calling and gives roughly 500 free requests
per day, with a 15-requests-per-minute ceiling discovered directly (a
429 RESOURCE_EXHAUSTED during eval development) rather than assumed from
documentation. The agent code has no hard dependency on this specific
provider — swapping models means changing where `genai.Client(...)` is
constructed, not rearchitecting the tools.

**Five read-only tools, nothing that acts on the user's behalf.**
`get_forecast`, `explain_forecast`, `get_reorder_status`,
`run_budget_optimization`, and `list_pending_recommendations` all wrap
already-tested service functions directly. Nothing approves, edits, or
rejects a real order — the system instruction explicitly tells the model
to say so and point the user to the Recommendations page if asked. This
was a deliberate scope boundary: an assistant that can look up and
explain is safe by default; one that can act on real purchase decisions
needs a substantially more deliberate trust model, treated here as
explicitly out of scope rather than quietly built in.

**Tenant scoping is enforced by construction, not by convention.** Each
`Assistant` is built once per chat session with a fixed `tenant_id`, and
every tool is a closure over that value — the LLM never sees or supplies
`tenant_id` as an argument to any tool, so it cannot be tricked into
crossing a tenant boundary by anything in the conversation. Verified with
a repeated check (10 runs, not one), since a single pass cannot rule out
a rare failure.

**Every tool creates its own database engine, scoped to whichever event
loop runs it, mirroring `workers/tasks_import.py`'s established pattern.**
An early version passed one `AsyncSession` into the `Assistant`
constructor and reused it from Gemini's synchronous tool-calling
callback; when that callback ran on a background thread (the thread-
bridging fallback for when an event loop is already active), the shared
`asyncpg` connection was used from a different loop than the one that
created it, corrupting its internal state
(`InterfaceError: cannot perform operation`). Each tool now opens, uses,
and disposes its own engine per call.

**A real debugging detour, worth recording precisely.** An early failing
test looked exactly like LLM non-determinism: the same question,
identical tenant and product, sometimes returned real data and sometimes
"no forecast available." Ten isolated single-process calls came back
10/10 correct, appearing to confirm the model was simply unreliable.
The actual cause was unrelated to the LLM entirely:
`tests/conftest.py` overrides `DATABASE_URL` to point at the separate,
empty `stockpilot_test` database for the whole pytest process, and the
first version of these tests hardcoded real product/tenant UUIDs from the
personal dev database — data that could never exist under pytest,
regardless of what the LLM did. The fix was not a retry or a tolerance
threshold; it was seeding real data inside the test itself, the same way
every other integration test in this project already does. The lesson:
a plausible-sounding explanation confirmed by a quick, narrow check
(direct calls succeeding outside pytest) is not the same as the real
root cause, and it is worth continuing to dig — cheaply, by checking the
actual database state — before accepting the first explanation that
fits the symptoms.

**The eval suite measures behavior, not a single pass/fail, and is
separate from pytest.** Four checks: grounded answers use real tool
output, the assistant does not fabricate data for a product that does
not exist, it does not falsely claim to have taken an action it cannot
take, and tenant isolation holds across ten repeated attempts, not one.
It seeds and tears down its own tenants, isolated from both the personal
dev database's real data and pytest's ephemeral test database. Not run
in CI, since it makes real, rate-limited API calls — the same category
as `scripts/run_simulation.py`, a manual verification tool rather than an
automated gate.

**A second real bug, found by the eval suite's own cleanup path**: the
first real end-to-end run left two orphaned tenants in the dev database,
because `_cleanup` deleted `tenants` rows before their dependent
`users`/`products`/etc. rows (a foreign-key violation) — and even once
ordering was fixed, every RLS-protected table needed
`set_config('app.current_tenant', ...)` set per tenant before its delete,
the same lesson from nearly every earlier week, now recurring in cleanup
code specifically rather than application code.

## Consequences

**The free tier's 15-requests-per-minute limit is a real, hard
constraint on the eval suite's design**, not just documentation. The
tenant-isolation check paces its ten calls with an explicit delay to stay
under it; a naive tight loop hit a 429 on the very first real run of the
finished suite.

**Free-tier model quality is genuinely a notch below a frontier model.**
Every scenario this suite tests passed, but the sample size (one run of
four checks, one ten-run isolation check) is not large enough to claim a
precise reliability percentage — it demonstrates the assistant behaves
correctly on the cases tested, not a statistically rigorous bound on how
often it might not.

**Architecture stays swappable.** Because every tool is a plain Python
function wrapping already-tested service code, and the model client is
constructed in one place, moving to a different or paid provider later —
should the project's needs change — is a small, contained change, not a
rewrite.
