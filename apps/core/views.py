"""Project-wide error handlers.

This is a JSON-only API — there are no templates, so Django's default HTML
error pages are never an acceptable response. These handlers cover the two
cases that sit *above* DRF's exception handling and therefore never reach a
DRF view:

- a routing-level 404 (the URL matched nothing in ``urlpatterns``)
- a genuinely unhandled exception (500)

Exceptions raised *inside* a DRF view (``NotFound``, ``ValidationError``, ...)
are already rendered as JSON by DRF's own exception handler.

Django only invokes these when ``DEBUG = False``; with ``DEBUG = True`` it
keeps showing its own debug pages, which is what we want in local dev.

``apps.core`` deliberately isn't in ``INSTALLED_APPS``: Django resolves
``handler404``/``handler500`` by importing the dotted path, so app
registration isn't needed (and there are no models/migrations here).
"""

from django.http import JsonResponse


def json_404(request, exception):
    return JsonResponse({"error": "Not found"}, status=404)


def json_500(request):
    return JsonResponse({"error": "Internal server error"}, status=500)
