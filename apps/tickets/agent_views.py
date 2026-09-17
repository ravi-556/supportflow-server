from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAgent
from apps.tickets import services
from apps.tickets.models import ReplyByRole, TicketActivity
from apps.tickets.serializers import (
    MessageCreateSerializer,
    MessageSerializer,
    TicketActivitySerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketListItemSerializer,
    TicketUpdateSerializer,
)


class TicketListView(APIView):
    permission_classes = [IsAgent]

    def get(self, request):
        qs = services.ticket_queryset().order_by("-created_at")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        # Plain APIView gets no free pagination from DEFAULT_PAGINATION_CLASS
        # (only generics do), so drive the paginator by hand. This is
        # HTTP-layer mechanics, deliberately not pushed into services.py.
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(TicketListItemSerializer(page, many=True).data)

    def post(self, request):
        payload = TicketCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ticket = services.create_ticket(**payload.validated_data)
        return Response(TicketDetailSerializer(ticket).data, status=201)


class TicketDetailView(APIView):
    permission_classes = [IsAgent]

    def get(self, request, ticket_id):
        ticket = services.get_ticket_or_404(ticket_id)
        return Response(TicketDetailSerializer(ticket).data)

    def patch(self, request, ticket_id):
        payload = TicketUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        ticket = services.update_ticket(
            ticket_id,
            status=data.get("status"),
            priority=data.get("priority"),
            agent_id=data["agent_id"] if "agent_id" in data else ...,
            group_id=data["group_id"] if "group_id" in data else ...,
            # Audit attribution comes from the JWT principal, never the request
            # body — otherwise any agent could pin a change on another agent.
            changed_by_agent_id=request.user.id,
        )
        return Response(TicketDetailSerializer(ticket).data)


class TicketMessageListView(APIView):
    permission_classes = [IsAgent]

    def get(self, request, ticket_id):
        messages = services.get_ticket_or_404(ticket_id).messages.order_by("created_at")
        return Response(MessageSerializer(messages, many=True).data)

    def post(self, request, ticket_id):
        payload = MessageCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        if data["reply_by"] == ReplyByRole.AGENT:
            # An agent reply is always authored by the caller. The serializer
            # only checks the *shape* (agent_id present, customer_id absent);
            # binding it to the authenticated principal is an authorization
            # concern, so it belongs here, not in validate(). reply_by
            # customer/system are left alone on purpose — an agent legitimately
            # logs messages on a customer's behalf (e.g. a phone call).
            data["agent_id"] = request.user.id
        message = services.create_message(ticket_id, **data)
        return Response(MessageSerializer(message).data, status=201)


class TicketActivityListView(APIView):
    permission_classes = [IsAgent]

    def get(self, request, ticket_id):
        activities = TicketActivity.objects.filter(ticket_id=ticket_id).order_by("-created_at")
        return Response(TicketActivitySerializer(activities, many=True).data)
