from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAgent
from apps.tickets import services
from apps.tickets.models import TicketActivity
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
        return Response(TicketListItemSerializer(qs, many=True).data)

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
            changed_by_agent_id=data.get("changed_by_agent_id"),
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
        message = services.create_message(ticket_id, **payload.validated_data)
        return Response(MessageSerializer(message).data, status=201)


class TicketActivityListView(APIView):
    permission_classes = [IsAgent]

    def get(self, request, ticket_id):
        activities = TicketActivity.objects.filter(ticket_id=ticket_id).order_by("-created_at")
        return Response(TicketActivitySerializer(activities, many=True).data)
