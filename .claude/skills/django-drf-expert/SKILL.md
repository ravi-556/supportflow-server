---
name: django-drf-expert
description: Django REST Framework conventions for this project's API-only backend — serializers, viewsets, ORM optimization, JSON error handling, testing, and security for a JWT-authenticated, no-template Django API. Use when writing or reviewing Django/DRF code in supportflow-server.
---

# Django DRF Expert

This is an API-only Django backend — no templates, no forms, no server-rendered pages. Everything below assumes that.

## Non-negotiable project conventions

These come from this codebase's own CLAUDE.md and hard-won bugs — they override any generic pattern in the reference files below if the two ever conflict:

- Business logic goes in `services.py`, not in views or in fat viewset methods (`get_queryset`/`perform_create`). Views parse the request, call a service function, return the response. Don't reach for ModelViewSet's queryset-based patterns as a substitute for this.
- Every endpoint sits under `/api/v1/agent/...` or `/api/v1/customer/...`, in separate `agent_views.py`/`customer_views.py` per app. `models.py`/`services.py` stay shared.
- `IsAgent`/`IsCustomer` (`apps/accounts/permissions.py`) enforce role on every view — never rely on the URL prefix alone.
- If you touch `JWTAuthentication` (`apps/accounts/authentication.py`): `authenticate()` must return `None` — never raise — on an expired/invalid token, and `authenticate_header()` must stay defined. Getting either wrong 403s a wrong token instead of 401ing it, or breaks `AllowAny` views outright. See `references/drf-guidelines.md`'s Authentication section for why.
- UUID primary keys are DB-generated (`gen_random_uuid()` / `default=uuid.uuid4`) — never hand-typed in seed data. `ticket_no` is a real Postgres sequence assigned in `services.py`, not a model default.
- No hand-written SQL schema — `makemigrations`/`migrate` from empty is the only path to the schema.
- No Redis and no Celery in this project yet — only Postgres runs in `docker-compose.yml`. Don't write code that assumes either is available.

## When to read which reference file

Don't load a reference file speculatively — read the one that matches what you're actually doing right now:

- **Writing or reviewing a serializer, viewset, permission, filter, pagination, or versioning** → `references/drf-guidelines.md`
- **Writing a view or wiring up a URL** (function view vs `APIView` vs `ViewSet`, thin-view/`services.py` split, JSON error handling, auth-failure responses) → `references/views-and-urls.md`
- **Writing a model, a query, or chasing a slow endpoint** (N+1s, `select_related`/`prefetch_related`, indexes, custom managers, bulk ops) → `references/models-and-orm.md`
- **Writing or reviewing tests** → `references/testing-strategies.md` (skip straight to its "API Testing (DRF)" section for endpoint tests; the file also covers model tests, Factory Boy, mocking, and coverage)
- **Touching auth, permissions, settings, or anything user-input-adjacent** → `references/security-checklist.md`
- **Something is slow, or you're adding caching/Celery/pagination at scale** → `references/performance-optimization.md`
- **You want a worked example of the request → response shape for a task** (model + manager, N+1 fix, full CRUD endpoint, endpoint tests) → `references/examples.md`

## A note on the reference files' origin

The reference files are adapted from a general-purpose Django-expert skill, trimmed for this project: HTML/template/forms content removed, and known conflicts with this codebase corrected directly in the files themselves rather than patched over here — DRF's generic `TokenAuthentication` example replaced with this project's actual `JWTAuthentication`, the generic `DEFAULT_VERSIONING_CLASS` example replaced with the literal-URL-prefix versioning actually used, and Celery/Redis sections flagged as not-yet-installed rather than presented as already available. If you spot another place a reference file assumes something this project doesn't have, fix the file — don't just note the gap here.
