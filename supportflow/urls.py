from django.db import connection
from django.http import JsonResponse
from django.urls import include, path


def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


# Two audience namespaces, kept separate all the way from the URL down to
# agent_views.py/customer_views.py in each app (models + services.py stay
# shared). If this ever needs to split into separate services, everything
# under one of these prefixes is what moves — no further untangling required.
agent_urlpatterns = [
    path("", include("apps.accounts.agent_urls")),
    path("", include("apps.tickets.agent_urls")),
]

customer_urlpatterns = [
    path("", include("apps.accounts.customer_urls")),
    path("", include("apps.support.customer_urls")),
    path("", include("apps.tickets.customer_urls")),
]

urlpatterns = [
    path("health", health),
    path("api/v1/agent/", include(agent_urlpatterns)),
    path("api/v1/customer/", include(customer_urlpatterns)),
]

# JSON-only API: a routing-level 404 (no urlpattern matched) and a true
# unhandled 500 never reach a DRF view, so DRF's exception handler can't
# render them — without these they'd fall back to Django's HTML error pages.
# Only used when DEBUG = False; the debug pages still apply in local dev.
handler404 = "apps.core.views.json_404"
handler500 = "apps.core.views.json_500"
