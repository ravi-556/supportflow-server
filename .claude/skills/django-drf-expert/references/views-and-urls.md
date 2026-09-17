# Django JSON API Views & URLs Best Practices

This project has no server-rendered pages — every view returns JSON. There are no templates, no forms, no context processors, and no `render()` calls anywhere in the API layer.

## Function-Based vs Class-Based Views (JSON)

**Use a function view (`@api_view`) when:**
- It's a single, custom endpoint that doesn't map to standard CRUD
- The logic is a one-off (a webhook, a stats endpoint, a "publish" action)

**Use `APIView` when:**
- One URL needs to handle multiple HTTP methods with related logic (GET + PATCH on the same resource)

**Use `ViewSet`/`ModelViewSet` when:**
- You need full CRUD on a resource and want router-based URL generation
- See `drf-guidelines.md` for serializer/permission/filtering patterns — this file only covers view/URL mechanics

```python
# ✅ GOOD: simple custom endpoint — function view
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ticket_stats(request):
    stats = get_ticket_stats(request.user)
    return Response(stats)

# ✅ GOOD: multiple methods on one resource — APIView
class TicketDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAgent]

    def get(self, request, ticket_id):
        ticket = get_ticket_or_404(ticket_id)
        return Response(TicketSerializer(ticket).data)

    def patch(self, request, ticket_id):
        ticket = update_ticket(ticket_id, request.data)
        return Response(TicketSerializer(ticket).data)
```

## Thin Views, Business Logic in `services.py`

The view's only job is: parse the request, call a service function, return a `Response`. Anything more than that belongs in `services.py`.

```python
# ❌ BAD: business logic embedded in the view
class TicketDetailView(APIView):
    def patch(self, request, ticket_id):
        ticket = Ticket.objects.get(id=ticket_id)
        if ticket.status == 'Resolved' and request.data.get('status') == 'Open':
            ticket.reopened_at = timezone.now()
            ticket.sla_due_at = calculate_sla_due(ticket)
        ticket.status = request.data.get('status', ticket.status)
        ticket.save()
        return Response(TicketSerializer(ticket).data)

# ✅ GOOD: view delegates to a service function
class TicketDetailView(APIView):
    def patch(self, request, ticket_id):
        ticket = update_ticket_status(ticket_id, request.data)
        return Response(TicketSerializer(ticket).data)

# services.py
def update_ticket_status(ticket_id, data):
    ticket = Ticket.objects.get(id=ticket_id)
    if ticket.status == 'Resolved' and data.get('status') == 'Open':
        ticket.reopened_at = timezone.now()
        ticket.sla_due_at = calculate_sla_due(ticket)
    ticket.status = data.get('status', ticket.status)
    ticket.save()
    return ticket
```

**Rule**: If a view method is more than "parse → call service → return Response", the extra logic belongs in `services.py`.

## URL Configuration

```python
from django.urls import path, include

app_name = 'tickets'  # ✅ GOOD: namespace your URLs

urlpatterns = [
    # ✅ GOOD: named patterns, explicit converters
    path('', views.TicketListView.as_view(), name='ticket_list'),
    path('<uuid:ticket_id>/', views.TicketDetailView.as_view(), name='ticket_detail'),
    path('<uuid:ticket_id>/messages/', views.TicketMessageListView.as_view(), name='ticket_messages'),
]
```

### URL Converters

- `<int:name>` — integers
- `<uuid:name>` — UUIDs (this project's PKs — see `models-and-orm.md`)
- `<slug:name>` — slugs
- `<str:name>` — any non-empty string excluding `/`

### Splitting by Portal

```python
# ✅ GOOD: separate URLconfs per portal, matching agent_views.py / customer_views.py
urlpatterns = [
    path('api/v1/agent/', include('apps.tickets.agent_urls')),
    path('api/v1/customer/', include('apps.tickets.customer_urls')),
]
```

### Reverse URL Resolution

```python
from django.urls import reverse

# ✅ GOOD: never hardcode URLs, even in a JSON API (redirects, generated links, tests)
def notify_ticket_url(ticket):
    return reverse('tickets:ticket_detail', kwargs={'ticket_id': ticket.id})
```

## JSON Responses & Status Codes

```python
from rest_framework.response import Response
from rest_framework import status

# ✅ GOOD: use DRF's Response, not raw JsonResponse, in any DRF view —
# it handles content negotiation and integrates with exception handling
class TicketListView(APIView):
    def post(self, request):
        ticket = create_ticket(request.data, request.user)
        return Response(TicketSerializer(ticket).data, status=status.HTTP_201_CREATED)

    def delete(self, request, ticket_id):
        delete_ticket(ticket_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

# ❌ BAD: raw JsonResponse in a DRF codebase — bypasses renderers,
# content negotiation, and the exception handler
from django.http import JsonResponse

def delete_ticket_view(request, ticket_id):
    delete_ticket(ticket_id)
    return JsonResponse({'status': 'deleted'})
```

**Rule**: `JsonResponse` is for plain Django views outside DRF (e.g. `handler404`/`handler500`, below). Inside DRF views, always return `Response`.

## Error Handling for JSON APIs

No `404.html`/`500.html` — unhandled errors and missing routes must still come back as JSON, not an HTML error page.

```python
# urls.py (project-level)
handler404 = 'apps.core.views.json_404'
handler500 = 'apps.core.views.json_500'

# apps/core/views.py
from django.http import JsonResponse

def json_404(request, exception):
    return JsonResponse({'error': 'Not found'}, status=404)

def json_500(request):
    return JsonResponse({'error': 'Internal server error'}, status=500)
```

For errors raised inside DRF views, use a custom exception handler instead of try/except in every view:

```python
# apps/core/exceptions.py
from rest_framework.views import exception_handler

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        response.data = {'error': response.data, 'status_code': response.status_code}
    return response

# settings.py
REST_FRAMEWORK = {
    'EXCEPTION_HANDLER': 'apps.core.exceptions.custom_exception_handler',
}
```

## Authentication & Authorization Errors — Never Redirect

```python
# ❌ BAD: @login_required redirects to an HTML login page —
# a JSON/API client gets a 302 to a page it can't render, not a 401
from django.contrib.auth.decorators import login_required

@login_required
def ticket_list(request):
    ...

# ✅ GOOD: DRF permission classes return 401/403 JSON, never a redirect
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ticket_list(request):
    ...
```

**Rule**: Every non-public view must be reachable only via DRF permission classes (`IsAgent`/`IsCustomer`/`IsAuthenticated`), never Django's `login_required`/`permission_required` decorators — those assume an HTML login page exists.

## Middleware

Middleware in a JSON API is still legitimate for cross-cutting concerns — just don't reach for it to touch HTML.

```python
# ✅ GOOD: request logging, agnostic to response format
class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        logger.info(f"{request.method} {request.path}")
        response = self.get_response(request)
        logger.info(f"Response: {response.status_code}")
        return response
```

## View Best Practices Checklist

✅ Views parse the request, call a `services.py` function, and return a `Response` — nothing more
✅ Every non-public endpoint uses DRF permission classes (401/403 JSON), never `login_required`
✅ `handler404`/`handler500` return JSON, not an HTML error page
✅ No `render()`, no `django.shortcuts.render`, no template anywhere in the API layer
✅ Use `Response` (DRF) inside DRF views; reserve `JsonResponse` for plain Django views like error handlers
✅ URL patterns are named and namespaced per portal (agent/customer)
✅ Log errors and security-relevant events without leaking sensitive fields
