# SupportFlow — Server (Django)

The backend REST API for SupportFlow, a Zendesk-style customer support ticketing system. Postgres via Docker. The Angular frontend lives in the separate `supportflow-client` repo (sibling folder in local dev: `../supportflow-client`).

Product/implementation specs (PRD, feature gap analysis, Zendesk/Freshdesk research) live in the separate `supportflow` planning folder, not in this repo — see `../supportflow/docs/`.

**Read `../supportflow/docs/zendesk_freshdesk_reference.md` before touching SLA logic, automation rules, portal features, or admin screens.** It's grounded research (real docs, not assumption) on how Zendesk/Freshdesk actually implement these — not recoverable by reading this codebase, since it's about behavior that hasn't been built yet.

## Conventions for new code

- Business logic goes in `services.py`, not in views — views just parse the request, call a service function, return the response.
- Every endpoint sits under `/api/v1/agent/...` or `/api/v1/customer/...`, down to separate `agent_views.py`/`customer_views.py` per app. `models.py`/`services.py` stay shared.
- `IsAgent`/`IsCustomer` (`apps/accounts/permissions.py`) enforce role on every view — don't rely on the URL prefix alone. Wrong/missing token → 401, wrong role → 403; if you touch `apps/accounts/authentication.py`, keep `authenticate_header()` or DRF silently collapses both to 403. Also keep `JWTAuthentication.authenticate()` returning `None` (not raising) on an expired/invalid token — raising there 401s an `AllowAny` view outright, since DRF runs authentication before permission checks. Bit us for real: a stale token sitting in a browser's `localStorage` broke every public endpoint (KB, CSAT) until this was fixed.
- No hand-written SQL schema — `makemigrations`/`migrate` from empty is the only path to the schema. `ticket_no` is a real Postgres sequence, assigned explicitly in `services.py` (see `tickets/migrations/0002_ticket_no_sequence.py`), not an implicit default.
- UUID primary keys are always DB-generated (`gen_random_uuid()` / `default=uuid.uuid4`) — never hand-type placeholder UUIDs in seed data.

## Workflow

- **Every feature is built on its own branch**, not directly on `main` — `git checkout -b feature/<name>` before starting, PRD spec in hand. Push it and open a PR on GitHub (`ravi-556/supportflow-server`) rather than merging locally. Don't merge or push to `main` without being asked.

## Dev environment

```bash
docker compose up -d postgres                       # Postgres, not installed on host
./.venv/bin/python manage.py runserver 127.0.0.1:8000
```

- Secrets in `.env` (not committed).
- DB: container `supportflow_postgres`, database `supportflow_django`.
- No fixtures/seed data — test rows were created by hand via `psql` during development and may not still exist.

## ⚠️ Before any real deployment

OTP codes are returned in the API response (`dev_otp` field) and printed to console — no email/SMS provider is wired up. Search `DEV ONLY` in `apps/accounts/`. Must be removed before this touches anything but localhost.
