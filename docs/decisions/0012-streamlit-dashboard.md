# 0012: Streamlit dashboard as the initial frontend

## Status
Accepted, with an explicit planned follow-up

## Context
Weeks 1-10 built a complete, tested backend: auth, tenant isolation,
forecasting, an optimizer, and an approval workflow, all served through a
REST API. None of it was visible or usable without curl or the API docs
page. Week 11 needed a real, clickable interface.

## Decision

**Streamlit, not a custom frontend, for this phase.** The dashboard is a
thin client: every page calls the existing, tested FastAPI endpoints over
plain HTTP with the same JWT auth already built, and contains no business
logic of its own (`dashboard/api_client.py` is a direct pass-through to
each endpoint). This was a deliberate scope choice, not an oversight — a
Streamlit app can be built and verified in a single session, keeping the
project's pace, and it is a legitimate way real companies ship internal
tools, not merely a toy.

**Four pages, covering the real day-to-day workflow**: sign in, an
overview of what needs attention, a per-product forecast chart with an
on-demand SHAP explanation, and a recommendations screen to generate,
approve, edit, or reject suggested orders. A what-if simulator (sliders
for budget or lead-time scenarios) was considered and explicitly not
built this week — it would need new backend support, since Week 10's
policy simulation currently only runs as a script, not an API endpoint,
and building that endpoint is a large enough piece of work to be its own
task rather than a Week 11 stretch goal.

**A real bug found and fixed while building this**: the pending
recommendations endpoint originally returned only a raw `product_id`,
making the list unreadable to an actual user (a wall of UUIDs, no product
names). Fixed by adding an optional `sku` field to
`OrderRecommendationOut`, populated via a join to `Product` in the
`pending`-list endpoint specifically, rather than forcing every endpoint
using that same response schema to pay for a join it does not need.

## Consequences

**Because the dashboard only talks to the API and owns no logic itself,
swapping it for a different frontend later is a frontend-only change.**
Every endpoint, every test, and all backend logic are already
independent of how they are displayed. This was a deliberate design
property, not an accident: it is the reason "Streamlit now, a proper
frontend later" is a genuine, low-risk option rather than a compromise
that locks the project into a look it will later need to unwind.

**Explicitly planned, not yet built**: a production-grade (React or
similar) frontend is a real candidate for a later phase, once Weeks 12-16
are secured, given how far ahead of the original schedule this project
already is. This is stated here plainly so it reads as a deliberate
staged plan, not an unfinished project.

**Not covered this week**: the what-if simulator page, and any automated
tests for the dashboard itself (Streamlit's UI code has limited unit-test
value; verification here was manual, against real CA_1 data, with each
page's real output checked against values already independently
confirmed via direct API calls in earlier weeks — for example, the SHAP
explanation numbers shown in the dashboard match the values verified by
hand in Week 8).
