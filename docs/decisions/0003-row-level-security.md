# 0003: Enforce tenant isolation with Postgres row-level security

Status: accepted
Date: 2026-09-21

## Context

Every tenant-scoped query needs `WHERE tenant_id = ...`. If one query forgets
it, one shop can read another shop's data, and no test fails unless it targets
that exact query. Application-level filtering is a rule developers must
remember every time.

## Decision

Add Postgres row-level security as a second layer, on `products` and
`suppliers`:

- A policy on each table limits every query to rows where `tenant_id` equals
  the `app.current_tenant` session setting. `WITH CHECK` also stops the app
  from writing rows for another tenant.
- `get_current_user` sets that setting on every authenticated request with
  `set_config(..., true)`, so it lasts only for the current transaction.
  Pooled connections cannot carry one shop's identity into another request.
- If the setting is missing, the policy matches nothing. A bug returns no
  rows, not everyone's rows.
- The app connects as `stockpilot_app`, a role with no superuser or
  BYPASSRLS rights. Migrations and test cleanup use the owner role.
- The `WHERE tenant_id = ...` filters stay. They are the first layer and RLS
  is the second.

## Consequences

Good:
- A forgotten filter no longer leaks data. Tests prove it: unfiltered
  SELECT and UPDATE statements only touch the current tenant's rows.
- Writes for another tenant are refused by the database.

Costs and known gaps:
- `users` and `tenants` are not covered. Login must find a user by email
  before it knows their tenant, so a simple policy would block it. These two
  tables still rely on application filters.
- Every new tenant table needs its own policy, and a migration that forgets
  it is unprotected. Later tenant tables should be checked for this.
- Code that runs outside a logged-in request (the event consumer in Week 4,
  Celery workers) must set `app.current_tenant` itself before touching
  tenant tables. Otherwise it sees nothing.
- The dev password for `stockpilot_app` is a local credential. Production
  needs a real secret (Week 15).
- The restricted role exists once per Postgres server, shared by the dev and
  test databases.