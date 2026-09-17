"""Tests for authentication, the 401-vs-403 distinction, and the OTP flows.

The 401/403 split is the highest-risk behaviour in this codebase (see
CLAUDE.md): `JWTAuthentication.authenticate()` must return None — never raise —
on a bad token, and `authenticate_header()` must stay defined. Getting either
wrong turns a stale token in a browser's localStorage into a hard failure on
every public endpoint. The `StaleTokenOnPublicEndpointTests` class below is the
regression guard for exactly that.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APITestCase

from apps.accounts.authentication import Principal
from apps.accounts.models import Agent, AgentRole, Customer, OtpCode, OtpPurpose
from apps.accounts.security import create_access_token, hash_password, hash_otp
from apps.accounts.throttles import AuthRateThrottle

# An AllowAny endpoint (apps.support.customer_views.KbArticleListView) and two
# role-gated ones. Referenced by literal path on purpose — the URL prefix is
# part of the contract being tested.
PUBLIC_URL = "/api/v1/customer/kb/articles"
AGENT_ONLY_URL = "/api/v1/agent/agents"
CUSTOMER_ONLY_URL = "/api/v1/customer/tickets"

AGENT_LOGIN_URL = "/api/v1/agent/auth/login"
AGENT_VERIFY_OTP_URL = "/api/v1/agent/auth/verify-otp"
CUSTOMER_REQUEST_OTP_URL = "/api/v1/customer/auth/request-otp"
CUSTOMER_VERIFY_OTP_URL = "/api/v1/customer/auth/verify-otp"
GUEST_TICKET_OTP_URL = "/api/v1/customer/guest-tickets/otp"
GUEST_TICKET_SUBMIT_URL = "/api/v1/customer/guest-tickets"


def make_agent(email="agent@example.com", password="s3cret-pw", role=AgentRole.AGENT) -> Agent:
    return Agent.objects.create(email=email, password_hash=hash_password(password), role=role)


def make_customer(email="customer@example.com") -> Customer:
    return Customer.objects.create(email=email)


def expired_token(*, subject: str, role: str) -> str:
    """A token that was validly signed but whose exp is in the past — what a
    week-old localStorage entry actually looks like."""
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": subject, "role": role, "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def wrong_secret_token(*, subject: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": subject, "role": role, "iat": now, "exp": now + timedelta(hours=1)},
        "not-the-real-signing-key",
        algorithm=settings.JWT_ALGORITHM,
    )


class StaleTokenOnPublicEndpointTests(APITestCase):
    """CLAUDE.md: 'Bit us for real' — a bad token must be indistinguishable
    from no token at all, so AllowAny views keep working."""

    def test_public_endpoint_without_any_token(self):
        response = self.client.get(PUBLIC_URL)
        self.assertEqual(response.status_code, 200)

    def test_public_endpoint_with_garbage_token(self):
        response = self.client.get(PUBLIC_URL, HTTP_AUTHORIZATION="Bearer not-a-jwt-at-all")
        self.assertEqual(response.status_code, 200)

    def test_public_endpoint_with_expired_token(self):
        customer = make_customer()
        token = expired_token(subject=str(customer.id), role="customer")
        response = self.client.get(PUBLIC_URL, HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 200)

    def test_public_endpoint_with_token_signed_by_wrong_secret(self):
        customer = make_customer()
        token = wrong_secret_token(subject=str(customer.id), role="customer")
        response = self.client.get(PUBLIC_URL, HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 200)

    def test_public_endpoint_with_malformed_authorization_scheme(self):
        response = self.client.get(PUBLIC_URL, HTTP_AUTHORIZATION="Basic dXNlcjpwYXNz")
        self.assertEqual(response.status_code, 200)

    def test_public_endpoint_with_valid_token_still_works(self):
        customer = make_customer()
        token = create_access_token(subject=str(customer.id), role="customer")
        response = self.client.get(PUBLIC_URL, HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 200)


class IsAgentPermissionTests(APITestCase):
    def setUp(self):
        self.agent = make_agent()
        self.customer = make_customer()

    def test_no_token_is_401(self):
        response = self.client.get(AGENT_ONLY_URL)
        self.assertEqual(response.status_code, 401)

    def test_no_token_response_carries_www_authenticate_challenge(self):
        """If authenticate_header() ever disappears, DRF silently downgrades
        this 401 to a 403 — assert on the header, not just the status."""
        response = self.client.get(AGENT_ONLY_URL)
        self.assertEqual(response["WWW-Authenticate"], "Bearer")

    def test_garbage_token_is_401_not_403(self):
        response = self.client.get(AGENT_ONLY_URL, HTTP_AUTHORIZATION="Bearer garbage")
        self.assertEqual(response.status_code, 401)

    def test_expired_token_is_401_not_403(self):
        token = expired_token(subject=str(self.agent.id), role=self.agent.role)
        response = self.client.get(AGENT_ONLY_URL, HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 401)

    def test_valid_customer_token_is_403(self):
        token = create_access_token(subject=str(self.customer.id), role="customer")
        response = self.client.get(AGENT_ONLY_URL, HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 403)

    def test_valid_agent_token_is_200(self):
        token = create_access_token(subject=str(self.agent.id), role=self.agent.role)
        response = self.client.get(AGENT_ONLY_URL, HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 200)

    def test_admin_and_light_agent_roles_also_pass(self):
        for role in (AgentRole.ADMIN, AgentRole.LIGHT_AGENT):
            with self.subTest(role=role):
                agent = make_agent(email=f"{role}@example.com", role=role)
                token = create_access_token(subject=str(agent.id), role=agent.role)
                response = self.client.get(AGENT_ONLY_URL, HTTP_AUTHORIZATION=f"Bearer {token}")
                self.assertEqual(response.status_code, 200)


class IsCustomerPermissionTests(APITestCase):
    def setUp(self):
        self.agent = make_agent()
        self.customer = make_customer()

    def test_no_token_is_401(self):
        response = self.client.get(CUSTOMER_ONLY_URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], "Bearer")

    def test_expired_token_is_401_not_403(self):
        token = expired_token(subject=str(self.customer.id), role="customer")
        response = self.client.get(CUSTOMER_ONLY_URL, HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 401)

    def test_valid_agent_token_is_403(self):
        token = create_access_token(subject=str(self.agent.id), role=self.agent.role)
        response = self.client.get(CUSTOMER_ONLY_URL, HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 403)

    def test_valid_customer_token_is_200(self):
        token = create_access_token(subject=str(self.customer.id), role="customer")
        response = self.client.get(CUSTOMER_ONLY_URL, HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 200)


class AgentLoginFlowTests(APITestCase):
    LOGIN_URL = "/api/v1/agent/auth/login"
    VERIFY_URL = "/api/v1/agent/auth/verify-otp"
    PASSWORD = "correct-horse-battery"

    def setUp(self):
        self.agent = make_agent(password=self.PASSWORD)

    def _login(self):
        return self.client.post(
            self.LOGIN_URL, {"email": self.agent.email, "password": self.PASSWORD}, format="json"
        )

    def test_login_then_verify_issues_a_working_token(self):
        login = self._login()
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.data["agent_id"], str(self.agent.id))
        self.assertTrue(login.data["otp_required"])

        verify = self.client.post(
            self.VERIFY_URL, {"agent_id": str(self.agent.id), "code": login.data["dev_otp"]}, format="json"
        )
        self.assertEqual(verify.status_code, 200)
        self.assertEqual(verify.data["role"], AgentRole.AGENT)

        token = verify.data["access_token"]
        protected = self.client.get(AGENT_ONLY_URL, HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(protected.status_code, 200)

    def test_verify_consumes_the_code_so_it_cannot_be_replayed(self):
        code = self._login().data["dev_otp"]
        first = self.client.post(
            self.VERIFY_URL, {"agent_id": str(self.agent.id), "code": code}, format="json"
        )
        self.assertEqual(first.status_code, 200)

        replay = self.client.post(
            self.VERIFY_URL, {"agent_id": str(self.agent.id), "code": code}, format="json"
        )
        self.assertEqual(replay.status_code, 400)

    def test_wrong_password_is_401(self):
        response = self.client.post(
            self.LOGIN_URL, {"email": self.agent.email, "password": "wrong"}, format="json"
        )
        self.assertEqual(response.status_code, 401)

    def test_unknown_email_is_401(self):
        response = self.client.post(
            self.LOGIN_URL, {"email": "nobody@example.com", "password": self.PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 401)

    def test_wrong_password_does_not_issue_an_otp(self):
        self.client.post(self.LOGIN_URL, {"email": self.agent.email, "password": "wrong"}, format="json")
        self.assertEqual(OtpCode.objects.count(), 0)

    def test_wrong_code_is_400_and_increments_attempts(self):
        self._login()
        response = self.client.post(
            self.VERIFY_URL, {"agent_id": str(self.agent.id), "code": "000000"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(OtpCode.objects.get().attempts, 1)

    def test_expired_code_is_400(self):
        code = self._login().data["dev_otp"]
        OtpCode.objects.update(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))

        response = self.client.post(
            self.VERIFY_URL, {"agent_id": str(self.agent.id), "code": code}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_too_many_attempts_is_400_even_with_the_right_code(self):
        code = self._login().data["dev_otp"]
        OtpCode.objects.update(attempts=settings.OTP_MAX_ATTEMPTS)

        response = self.client.post(
            self.VERIFY_URL, {"agent_id": str(self.agent.id), "code": code}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_verify_without_any_pending_code_is_400(self):
        response = self.client.post(
            self.VERIFY_URL, {"agent_id": str(self.agent.id), "code": "123456"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_agent_code_cannot_be_redeemed_on_the_customer_endpoint(self):
        """Purposes are scoped per subject — an agent's verification code is
        not a customer login code."""
        code = self._login().data["dev_otp"]
        customer = make_customer()
        response = self.client.post(
            "/api/v1/customer/auth/verify-otp",
            {"customer_id": str(customer.id), "code": code},
            format="json",
        )
        self.assertEqual(response.status_code, 400)


class CustomerOtpFlowTests(APITestCase):
    REQUEST_URL = "/api/v1/customer/auth/request-otp"
    VERIFY_URL = "/api/v1/customer/auth/verify-otp"

    def setUp(self):
        self.customer = make_customer()

    def test_request_then_verify_issues_a_working_token(self):
        requested = self.client.post(self.REQUEST_URL, {"email": self.customer.email}, format="json")
        self.assertEqual(requested.status_code, 200)
        self.assertEqual(requested.data["customer_id"], str(self.customer.id))

        verify = self.client.post(
            self.VERIFY_URL,
            {"customer_id": str(self.customer.id), "code": requested.data["dev_otp"]},
            format="json",
        )
        self.assertEqual(verify.status_code, 200)
        self.assertEqual(verify.data["role"], "customer")

        token = verify.data["access_token"]
        protected = self.client.get(CUSTOMER_ONLY_URL, HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(protected.status_code, 200)

    def test_customer_token_is_not_accepted_on_agent_endpoints(self):
        requested = self.client.post(self.REQUEST_URL, {"email": self.customer.email}, format="json")
        verify = self.client.post(
            self.VERIFY_URL,
            {"customer_id": str(self.customer.id), "code": requested.data["dev_otp"]},
            format="json",
        )
        token = verify.data["access_token"]
        response = self.client.get(AGENT_ONLY_URL, HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 403)

    def test_unknown_email_is_404(self):
        response = self.client.post(self.REQUEST_URL, {"email": "nobody@example.com"}, format="json")
        self.assertEqual(response.status_code, 404)

    def test_wrong_code_is_400(self):
        requested = self.client.post(self.REQUEST_URL, {"email": self.customer.email}, format="json")
        bad_code = "000000" if requested.data["dev_otp"] != "000000" else "111111"

        response = self.client.post(
            self.VERIFY_URL, {"customer_id": str(self.customer.id), "code": bad_code}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(OtpCode.objects.get().attempts, 1)

    def test_expired_code_is_400(self):
        requested = self.client.post(self.REQUEST_URL, {"email": self.customer.email}, format="json")
        OtpCode.objects.update(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))

        response = self.client.post(
            self.VERIFY_URL,
            {"customer_id": str(self.customer.id), "code": requested.data["dev_otp"]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_too_many_attempts_is_400(self):
        requested = self.client.post(self.REQUEST_URL, {"email": self.customer.email}, format="json")
        OtpCode.objects.update(attempts=settings.OTP_MAX_ATTEMPTS)

        response = self.client.post(
            self.VERIFY_URL,
            {"customer_id": str(self.customer.id), "code": requested.data["dev_otp"]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_email_is_400(self):
        response = self.client.post(self.REQUEST_URL, {}, format="json")
        self.assertEqual(response.status_code, 400)


class OtpStorageTests(TestCase):
    """The raw code must never hit the database — only its hash."""

    def test_requesting_a_code_stores_only_the_hash(self):
        customer = make_customer()
        client_response = self.client.post(
            "/api/v1/customer/auth/request-otp",
            data={"email": customer.email},
            content_type="application/json",
        )
        code = client_response.json()["dev_otp"]

        otp = OtpCode.objects.get()
        self.assertEqual(otp.purpose, OtpPurpose.CUSTOMER_LOGIN)
        self.assertEqual(otp.code_hash, hash_otp(code))
        self.assertNotIn(code, otp.code_hash)


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
