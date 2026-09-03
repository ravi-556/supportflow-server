from rest_framework import serializers

from apps.tickets.models import Message, ReplyByRole, Ticket, TicketActivity


class TicketListItemSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(read_only=True)
    customer_email = serializers.CharField(read_only=True)
    agent_name = serializers.CharField(read_only=True)
    group_name = serializers.CharField(read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id",
            "ticket_no",
            "subject",
            "status",
            "priority",
            "customer_id",
            "customer_name",
            "customer_email",
            "agent_id",
            "agent_name",
            "group_id",
            "group_name",
            "resolution_sla_time",
            "created_at",
            "updated_at",
        ]


class TicketDetailSerializer(TicketListItemSerializer):
    # PRD §13.5 addendum — surfaces the CSAT link on the agent sidebar since
    # there's no email to click yet. Rides on this existing GET response,
    # no new endpoint. ticket.reviews.first() is safe as "the" review: at
    # most one exists per ticket, per create_pending_review's get_or_create.
    csat = serializers.SerializerMethodField()

    class Meta(TicketListItemSerializer.Meta):
        fields = TicketListItemSerializer.Meta.fields + [
            "ticket_type",
            "source",
            "parent_ticket_id",
            "first_responded_at",
            "resolved_at",
            "closed_at",
            "first_response_sla_time",
            "csat",
        ]

    def get_csat(self, obj) -> dict | None:
        review = obj.reviews.first()
        if review is None:
            return None
        return {"review_id": str(review.id), "submitted": review.submitted_at is not None, "score": review.score}


class TicketCreateSerializer(serializers.Serializer):
    subject = serializers.CharField()
    customer_id = serializers.UUIDField()
    priority = serializers.ChoiceField(choices=Ticket.priority.field.choices, required=False, default="medium")
    ticket_type = serializers.CharField(required=False, allow_null=True, default=None)
    source = serializers.ChoiceField(choices=Ticket.source.field.choices, required=False, default="agent")
    group_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    agent_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    # The ticket's first message — every ticket must open with content.
    initial_message = serializers.CharField()


class TicketUpdateSerializer(serializers.Serializer):
    """All fields optional — PATCH semantics, only send what changed.

    changed_by_agent_id isn't a model field; it's who to attribute the
    resulting ticket_activities rows to. Stand-in for real auth context.
    """

    status = serializers.ChoiceField(choices=Ticket.status.field.choices, required=False)
    priority = serializers.ChoiceField(choices=Ticket.priority.field.choices, required=False)
    agent_id = serializers.UUIDField(required=False, allow_null=True)
    group_id = serializers.UUIDField(required=False, allow_null=True)
    changed_by_agent_id = serializers.UUIDField(required=False, allow_null=True)


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id",
            "ticket_id",
            "description",
            "reply_by",
            "customer_id",
            "agent_id",
            "is_private",
            "created_at",
        ]


class MessageCreateSerializer(serializers.Serializer):
    description = serializers.CharField()
    reply_by = serializers.ChoiceField(choices=ReplyByRole.choices)
    customer_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    agent_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    is_private = serializers.BooleanField(default=False)
    # PRD: @mentions only exist inside private notes. Real @name parsing is
    # deferred — the client resolves names to ids and passes them explicitly.
    mentioned_agent_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)

    def validate(self, attrs):
        # Mirrors the DB CheckConstraint (messages_author_matches_role) so a
        # bad request fails fast with a clear 400 instead of a raw DB error.
        reply_by = attrs["reply_by"]
        customer_id, agent_id = attrs.get("customer_id"), attrs.get("agent_id")
        if reply_by == ReplyByRole.CUSTOMER and not (customer_id and not agent_id):
            raise serializers.ValidationError("reply_by=customer requires customer_id and no agent_id")
        if reply_by == ReplyByRole.AGENT and not (agent_id and not customer_id):
            raise serializers.ValidationError("reply_by=agent requires agent_id and no customer_id")
        if reply_by == ReplyByRole.SYSTEM and (customer_id or agent_id):
            raise serializers.ValidationError("reply_by=system must not set customer_id or agent_id")
        if attrs.get("mentioned_agent_ids") and not attrs.get("is_private"):
            raise serializers.ValidationError("mentions are only allowed on private notes")
        return attrs


class CustomerTicketListItemSerializer(serializers.ModelSerializer):
    """Deliberately narrower than TicketListItemSerializer — no priority,
    agent_name, or group_name. PRD §13.2: those are internal fields a
    customer must never see (§8.2 visibility rule), not just a smaller
    payload for convenience."""

    class Meta:
        model = Ticket
        fields = ["id", "ticket_no", "subject", "status", "updated_at"]


class CustomerTicketCreateSerializer(serializers.Serializer):
    subject = serializers.CharField()
    description = serializers.CharField()
    ticket_type = serializers.ChoiceField(
        choices=Ticket.ticket_type.field.choices, required=False, allow_null=True, default=None
    )


class CustomerMessageSerializer(serializers.ModelSerializer):
    """PRD §13.3 — deliberately does not reuse MessageSerializer, which
    exposes is_private/agent_id/customer_id directly. agent_name only (never
    agent_id), and only when reply_by=agent, matching the end-user thread
    view Zendesk shows (who helped, not the agent's account)."""

    agent_name = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ["id", "description", "reply_by", "agent_name", "created_at"]

    def get_agent_name(self, obj) -> str | None:
        if obj.reply_by != ReplyByRole.AGENT or not obj.agent_id:
            return None
        name = " ".join(filter(None, [obj.agent.first_name, obj.agent.last_name]))
        return name or obj.agent.email


class CustomerMessageCreateSerializer(serializers.Serializer):
    # No reply_by/is_private/agent_id/mentioned_agent_ids — narrower than
    # MessageCreateSerializer on purpose; a customer can only ever post a
    # public reply as themselves.
    description = serializers.CharField()


class GuestTicketSubmitSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField()
    subject = serializers.CharField()
    description = serializers.CharField()
    ticket_type = serializers.ChoiceField(
        choices=Ticket.ticket_type.field.choices, required=False, allow_null=True, default=None
    )


class TicketActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketActivity
        fields = [
            "id",
            "ticket_id",
            "action_type",
            "agent_id",
            "status_change",
            "priority_change",
            "sla_change",
            "created_at",
        ]
