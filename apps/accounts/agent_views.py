from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import services
from apps.accounts.models import Agent, Customer, Group
from apps.accounts.permissions import IsAgent
from apps.accounts.serializers import (
    AgentLoginRequestSerializer,
    AgentLoginResponseSerializer,
    AgentOtpVerifyRequestSerializer,
    AgentSerializer,
    CustomerSerializer,
    GroupSerializer,
    TokenResponseSerializer,
)
from apps.accounts.throttles import AuthRateThrottle


class AgentLoginView(APIView):
    permission_classes = [AllowAny]
    # Password check with no per-account lockout — the per-IP throttle is the
    # only thing standing between this and offline-speed credential stuffing.
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        payload = AgentLoginRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        agent, code = services.agent_login(**payload.validated_data)
        # DEV ONLY: no email/SMS provider wired up, so the code rides in the
        # response instead of actually being sent. Remove before this touches
        # anything but local dev.
        out = AgentLoginResponseSerializer({"agent_id": agent.id, "otp_required": True, "dev_otp": code})
        return Response(out.data)


class AgentVerifyOtpView(APIView):
    permission_classes = [AllowAny]
    # OTP_MAX_ATTEMPTS caps guesses against one OTP record; this caps how fast
    # an attacker can burn through freshly issued ones.
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        payload = AgentOtpVerifyRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        agent, token = services.agent_verify_otp(**payload.validated_data)
        out = TokenResponseSerializer({"access_token": token, "token_type": "bearer", "role": agent.role})
        return Response(out.data)


# --- Lookups (used by agent-side dropdowns/context — matches the old FastAPI lookups router) ---


class AgentListView(ListAPIView):
    permission_classes = [IsAgent]
    serializer_class = AgentSerializer
    # Paginated by REST_FRAMEWORK["DEFAULT_PAGINATION_CLASS"]; the explicit
    # order_by is what keeps page 2 from repeating rows from page 1 (an
    # unordered queryset has no stable LIMIT/OFFSET window).
    queryset = Agent.objects.filter(deactivated_at__isnull=True).order_by("email")


class GroupListView(ListAPIView):
    permission_classes = [IsAgent]
    serializer_class = GroupSerializer
    queryset = Group.objects.order_by("name")


class CustomerDetailView(RetrieveAPIView):
    permission_classes = [IsAgent]
    serializer_class = CustomerSerializer
    queryset = Customer.objects.all()
    lookup_url_kwarg = "customer_id"
