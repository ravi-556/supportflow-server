import uuid

from django.core.cache import cache
from rest_framework.test import APITestCase

from apps.accounts.authentication import Principal
from apps.accounts.throttles import AuthRateThrottle

AGENT_LOGIN_URL = "/api/v1/agent/auth/login"
AGENT_VERIFY_OTP_URL = "/api/v1/agent/auth/verify-otp"
CUSTOMER_REQUEST_OTP_URL = "/api/v1/customer/auth/request-otp"
CUSTOMER_VERIFY_OTP_URL = "/api/v1/customer/auth/verify-otp"
GUEST_TICKET_OTP_URL = "/api/v1/customer/guest-tickets/otp"
GUEST_TICKET_SUBMIT_URL = "/api/v1/customer/guest-tickets"


class ThrottleTestCase(APITestCase):
    """Throttle history lives in Django's cache (LocMemCache by default), which
    is process-global and would otherwise leak between tests."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)


class AuthRateThrottleTests(ThrottleTestCase):
    def test_login_is_throttled_after_the_configured_rate(self):
        # Empty body -> 400 from the serializer, but throttling runs in
        # APIView.initial() before the handler, so rejected requests still
        # count. That's the point: brute force attempts are all failures.
        for i in range(10):
            response = self.client.post(AGENT_LOGIN_URL, {}, format="json")
            self.assertNotEqual(response.status_code, 429, f"throttled early on request {i + 1}")

        response = self.client.post(AGENT_LOGIN_URL, {}, format="json")
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)

    def test_budget_is_shared_across_all_auth_endpoints(self):
        # One scope, one per-IP counter — rotating endpoints must not buy an
        # attacker a fresh 10 requests each.
        urls = [
            AGENT_LOGIN_URL,
            AGENT_VERIFY_OTP_URL,
            CUSTOMER_REQUEST_OTP_URL,
            CUSTOMER_VERIFY_OTP_URL,
            GUEST_TICKET_OTP_URL,
            GUEST_TICKET_SUBMIT_URL,
        ]
        for i in range(10):
            response = self.client.post(urls[i % len(urls)], {}, format="json")
            self.assertNotEqual(response.status_code, 429, f"throttled early on request {i + 1}")

        for url in urls:
            self.assertEqual(self.client.post(url, {}, format="json").status_code, 429, url)

    def test_throttle_is_not_bypassed_by_presenting_a_valid_token(self):
        # AnonRateThrottle's stock get_cache_key returns None for an
        # authenticated request; AuthRateThrottle overrides that, otherwise
        # any valid Bearer token would disable the limit on these AllowAny
        # views. Regression guard for exactly that.
        self.client.force_authenticate(user=Principal(subject_id=uuid.uuid4(), role="customer"))
        for _ in range(10):
            self.client.post(AGENT_LOGIN_URL, {}, format="json")

        response = self.client.post(AGENT_LOGIN_URL, {}, format="json")
        self.assertEqual(response.status_code, 429)

    def test_authenticated_non_auth_endpoints_are_not_throttled(self):
        # No DEFAULT_THROTTLE_CLASSES — ordinary agent traffic must stay
        # unlimited. 20 > the 10/min auth budget.
        self.client.force_authenticate(user=Principal(subject_id=uuid.uuid4(), role="agent"))
        for i in range(20):
            response = self.client.get("/api/v1/agent/groups")
            self.assertEqual(response.status_code, 200, f"request {i + 1} -> {response.status_code}")

    def test_scope_rate_is_configured(self):
        self.assertEqual(AuthRateThrottle.scope, "auth")
        throttle = AuthRateThrottle()
        self.assertEqual((throttle.num_requests, throttle.duration), (10, 60))
