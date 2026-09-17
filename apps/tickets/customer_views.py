from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import services as accounts_services
from apps.accounts.permissions import IsCustomer
from apps.accounts.security import create_access_token
from apps.accounts.serializers import GuestTicketOtpRequestResponseSerializer, GuestTicketOtpRequestSerializer
from apps.accounts.throttles import AuthRateThrottle
from apps.tickets import services
from apps.tickets.models import PriorityLevel, ReplyByRole, TicketSource
from apps.tickets.serializers import (
    CustomerMessageCreateSerializer,
    CustomerMessageSerializer,
    CustomerTicketCreateSerializer,
    CustomerTicketListItemSerializer,
    GuestTicketSubmitSerializer,
)


class CustomerTicketListView(APIView):
    """PRD §13.1 (POST) + §13.2 (GET) — same class, same URL, mirroring how
    agent_views.TicketListView already handles both verbs on
    /api/v1/agent/tickets."""

    permission_classes = [IsCustomer]

    def get(self, request):
        status_group = request.query_params.get("status_group")
        tickets = services.customer_ticket_queryset(request.user.id, status_group=status_group)
        return Response(CustomerTicketListItemSerializer(tickets, many=True).data)

    def post(self, request):
        payload = CustomerTicketCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        ticket = services.create_ticket(
            subject=data["subject"],
            customer_id=request.user.id,
            priority=PriorityLevel.MEDIUM,
            ticket_type=data["ticket_type"],
            source=TicketSource.PORTAL,
            group_id=None,
            agent_id=None,
            initial_message=data["description"],
        )
        return Response(CustomerTicketListItemSerializer(ticket).data, status=201)


class CustomerTicketDetailView(APIView):
    """PRD §13.3 — GET only, deliberately no PATCH; customers cannot change
    ticket properties (that's §8.2/§5.2's agent-only property list)."""

    permission_classes = [IsCustomer]

    def get(self, request, ticket_id):
        ticket = services.get_customer_ticket_or_404(ticket_id, request.user.id)
        return Response(CustomerTicketListItemSerializer(ticket).data)


class CustomerTicketMessageListView(APIView):
    permission_classes = [IsCustomer]

    def get(self, request, ticket_id):
        ticket = services.get_customer_ticket_or_404(ticket_id, request.user.id)
        # is_private=False is the one line standing between this endpoint
        # and a §8.2 visibility-rule violation — not optional.
        messages = ticket.messages.filter(is_private=False).select_related("agent").order_by("created_at")
        return Response(CustomerMessageSerializer(messages, many=True).data)

    def post(self, request, ticket_id):
        ticket = services.get_customer_ticket_or_404(ticket_id, request.user.id)
        payload = CustomerMessageCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        # Every field besides description is hardcoded here, never read from
        # the request body — a customer can't set is_private or forge
        # agent_id because the serializer never exposes those fields to
        # accept in the first place, not because of a runtime check.
        message = services.create_message(
            ticket.id,
            description=payload.validated_data["description"],
            reply_by=ReplyByRole.CUSTOMER,
            customer_id=request.user.id,
            agent_id=None,
            is_private=False,
            mentioned_agent_ids=[],
        )
        return Response(CustomerMessageSerializer(message).data, status=201)


class GuestTicketOtpRequestView(APIView):
    """PRD §13.1 revision — a not-signed-in visitor verifies their email
    inline (anti-spam gate) instead of being redirected to a separate login
    screen. get_or_create means this also covers a brand-new customer's
    very first contact, not just returning ones."""

    permission_classes = [AllowAny]
    # get_or_create means an unthrottled caller can also mass-create Customer
    # rows here, not just spam OTP emails.
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        payload = GuestTicketOtpRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        _, code = accounts_services.guest_ticket_request_otp(**payload.validated_data)
        return Response(GuestTicketOtpRequestResponseSerializer({"dev_otp": code}).data)


class GuestTicketSubmitView(APIView):
    """Verifies the OTP and creates the ticket in one request, then issues a
    session token — the visitor ends up signed in as a side effect, so their
    guest ticket is already there when they check My Tickets later."""

    permission_classes = [AllowAny]
    # Verifies an OTP *and* issues an access token — same brute-force surface
    # as the dedicated verify endpoints, plus anonymous ticket creation.
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        payload = GuestTicketSubmitSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        customer = accounts_services.verify_guest_ticket_otp(data["email"], data["code"])
        ticket = services.create_ticket(
            subject=data["subject"],
            customer_id=customer.id,
            priority=PriorityLevel.MEDIUM,
            ticket_type=data["ticket_type"],
            source=TicketSource.PORTAL,
            group_id=None,
            agent_id=None,
            initial_message=data["description"],
        )
        token = create_access_token(subject=str(customer.id), role="customer")
        return Response(
            {
                "ticket": CustomerTicketListItemSerializer(ticket).data,
                "access_token": token,
                "token_type": "bearer",
                "role": "customer",
            },
            status=201,
        )
