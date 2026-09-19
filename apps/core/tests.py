import json

from django.test import RequestFactory, SimpleTestCase

from supportflow import urls as project_urls

from .views import json_404, json_500


class JsonErrorHandlerTests(SimpleTestCase):
    """Routing-level errors must be JSON — these never reach a DRF view."""

    def test_handlers_are_wired_into_the_root_urlconf(self):
        self.assertEqual(project_urls.handler404, "apps.core.views.json_404")
        self.assertEqual(project_urls.handler500, "apps.core.views.json_500")

    def test_unmatched_route_returns_json_404(self):
        # The test runner forces DEBUG = False, which is when Django uses
        # handler404 instead of its own HTML debug page.
        response = self.client.get("/no/such/route")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {"error": "Not found"})

    def test_unmatched_api_route_returns_json_404(self):
        response = self.client.get("/api/v1/agent/does-not-exist")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Not found"})

    def test_json_404_handler_renders_json(self):
        request = RequestFactory().get("/no/such/route")

        response = json_404(request, Exception("boom"))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_json_500_handler_renders_json(self):
        request = RequestFactory().get("/boom")

        response = json_500(request)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(json.loads(response.content), {"error": "Internal server error"})
