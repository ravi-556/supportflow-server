import uuid

from django.db import models

from apps.accounts.models import Agent, Customer, Group


class TicketStatus(models.TextChoices):
    OPEN = "open"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"


class PriorityLevel(models.TextChoices):
    URGENT = "urgent"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TicketType(models.TextChoices):
    QUESTION = "question"
    INCIDENT = "incident"
    BUG = "bug"
    FEATURE_REQUEST = "feature_request"


class TicketSource(models.TextChoices):
    EMAIL = "email"
    PORTAL = "portal"
    CHAT = "chat"
    AGENT = "agent"


class ReplyByRole(models.TextChoices):
    CUSTOMER = "customer"
    AGENT = "agent"
    SYSTEM = "system"


class MessageStatus(models.TextChoices):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    FAILED = "failed"


class MentionStatus(models.TextChoices):
    UNREAD = "unread"
    READ = "read"


class ActivityActionType(models.TextChoices):
    TICKET_CREATED = "ticket_created"
    STATUS_CHANGE = "status_change"
    PRIORITY_CHANGE = "priority_change"
    ASSIGNMENT_CHANGE = "assignment_change"
    TAG_CHANGE = "tag_change"
    SLA_PAUSED = "sla_paused"
    SLA_RESUMED = "sla_resumed"
    TICKET_SPLIT = "ticket_split"


class SlaPolicy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    priority = models.CharField(max_length=20, choices=PriorityLevel.choices)
    first_response_time = models.DecimalField(max_digits=10, decimal_places=2)  # minutes
    resolution_time = models.DecimalField(max_digits=10, decimal_places=2)  # minutes
    business_hours_only = models.BooleanField(default=True)

    class Meta:
        db_table = "sla_policies"


class Tag(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tags"

    def __str__(self) -> str:
        return self.name


class Ticket(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Real auto-incrementing sequence, set up in tickets/migrations/0002_ticket_no_sequence.py
    # — NOT assigned in application code, to stay race-condition-safe under concurrent creates.
    ticket_no = models.PositiveBigIntegerField(unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="tickets")
    agent = models.ForeignKey(Agent, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")
    group = models.ForeignKey(Group, null=True, blank=True, on_delete=models.SET_NULL, related_name="tickets")
    subject = models.CharField(max_length=500)
    status = models.CharField(max_length=20, choices=TicketStatus.choices, default=TicketStatus.OPEN)
    priority = models.CharField(max_length=20, choices=PriorityLevel.choices, default=PriorityLevel.MEDIUM)
    ticket_type = models.CharField(max_length=30, choices=TicketType.choices, null=True, blank=True)
    source = models.CharField(max_length=20, choices=TicketSource.choices)
    parent_ticket = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="split_children"
    )
    tags = models.ManyToManyField(Tag, related_name="tickets", blank=True)
    first_responded_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    first_response_sla_time = models.DateTimeField(null=True, blank=True)
    resolution_sla_time = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tickets"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["priority"]),
            models.Index(fields=["group"]),
            models.Index(fields=["agent"]),
            models.Index(fields=["customer"]),
            models.Index(fields=["resolution_sla_time"]),
        ]

    def __str__(self) -> str:
        return f"#{self.ticket_no} {self.subject}"

    # Display-only convenience fields for list/detail API responses — read via
    # select_related in the queryset (see tickets/services.py) so these don't
    # trigger N+1 queries.
    @property
    def customer_email(self) -> str | None:
        return self.customer.email if self.customer_id else None

    @property
    def customer_name(self) -> str | None:
        if not self.customer_id:
            return None
        name = " ".join(filter(None, [self.customer.first_name, self.customer.last_name]))
        return name or self.customer.email

    @property
    def agent_name(self) -> str | None:
        if not self.agent_id:
            return None
        name = " ".join(filter(None, [self.agent.first_name, self.agent.last_name]))
        return name or self.agent.email

    @property
    def group_name(self) -> str | None:
        return self.group.name if self.group_id else None


class Message(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    description = models.TextField()
    reply_by = models.CharField(max_length=20, choices=ReplyByRole.choices)
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    agent = models.ForeignKey(Agent, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages")
    is_private = models.BooleanField(default=False)
    reply_to = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="replies")
    status = models.CharField(max_length=20, choices=MessageStatus.choices, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "messages"
        indexes = [models.Index(fields=["ticket"])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(reply_by="customer") & models.Q(customer__isnull=False) & models.Q(agent__isnull=True))
                    | (models.Q(reply_by="agent") & models.Q(agent__isnull=False) & models.Q(customer__isnull=True))
                    | (models.Q(reply_by="system") & models.Q(customer__isnull=True) & models.Q(agent__isnull=True))
                ),
                name="messages_author_matches_role",
            )
        ]


class TicketAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    message = models.ForeignKey(
        Message, null=True, blank=True, on_delete=models.CASCADE, related_name="attachments"
    )
    filename = models.CharField(max_length=500)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=200, null=True, blank=True)
    uploaded_by = models.ForeignKey(
        Agent, null=True, blank=True, on_delete=models.SET_NULL, related_name="uploaded_attachments"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    # See the same note as the FastAPI version: fine for now, swap for object
    # storage + a storage_key field before real files are involved.
    file = models.BinaryField(null=True, blank=True)

    class Meta:
        db_table = "ticket_attachments"


class Mention(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="mentions")
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="mentions")
    mentioned_by_agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="mentions_made")
    mentioned_agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="mentions_received")
    status = models.CharField(max_length=20, choices=MentionStatus.choices, default=MentionStatus.UNREAD)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mentions"
        indexes = [models.Index(fields=["mentioned_agent", "status"])]


class TicketActivity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="activities")
    action_type = models.CharField(max_length=30, choices=ActivityActionType.choices)
    agent = models.ForeignKey(Agent, null=True, blank=True, on_delete=models.SET_NULL, related_name="activities")
    status_change = models.CharField(max_length=200, null=True, blank=True)
    priority_change = models.CharField(max_length=200, null=True, blank=True)
    sla_change = models.CharField(max_length=200, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ticket_activities"
        indexes = [models.Index(fields=["ticket"])]
