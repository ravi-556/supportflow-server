import uuid

from django.db import models


class CustomerSegment(models.TextChoices):
    STANDARD = "standard"
    VIP = "vip"


class AgentRole(models.TextChoices):
    ADMIN = "admin"
    AGENT = "agent"
    LIGHT_AGENT = "light_agent"


class GroupCategory(models.TextChoices):
    BILLING = "billing"
    TECHNICAL = "technical"
    ONBOARDING = "onboarding"
    GENERAL = "general"


class OtpPurpose(models.TextChoices):
    AGENT_LOGIN_VERIFICATION = "agent_login_verification"
    CUSTOMER_LOGIN = "customer_login"
    CUSTOMER_TICKET_SUBMISSION = "customer_ticket_submission"


class Customer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    mobile = models.CharField(max_length=32, null=True, blank=True)
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    company = models.CharField(max_length=200, null=True, blank=True)
    segment = models.CharField(max_length=20, choices=CustomerSegment.choices, default=CustomerSegment.STANDARD)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "customers"

    def __str__(self) -> str:
        return self.email


class Agent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    mobile = models.CharField(max_length=32, null=True, blank=True)
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    role = models.CharField(max_length=20, choices=AgentRole.choices, default=AgentRole.AGENT)
    # Agents: password + OTP second factor. Customers: OTP only, never get one of these.
    password_hash = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "agents"

    def __str__(self) -> str:
        return self.email


class Group(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=GroupCategory.choices, null=True, blank=True)
    admin = models.ForeignKey(
        Agent, null=True, blank=True, on_delete=models.SET_NULL, related_name="administered_groups"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "groups"

    def __str__(self) -> str:
        return self.name


class GroupAgent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="group_agents")
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="group_agents")
    created_at = models.DateTimeField(auto_now_add=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "group_agents"
        constraints = [models.UniqueConstraint(fields=["group", "agent"], name="uq_group_agents_group_agent")]


class OtpCode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agent = models.ForeignKey(Agent, null=True, blank=True, on_delete=models.CASCADE, related_name="otp_codes")
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.CASCADE, related_name="otp_codes")
    purpose = models.CharField(max_length=40, choices=OtpPurpose.choices)
    # Never store the raw code — same principle as password_hash.
    code_hash = models.CharField(max_length=64)
    attempts = models.IntegerField(default=0)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "otp_codes"
        indexes = [models.Index(fields=["agent"]), models.Index(fields=["customer"])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(agent__isnull=False) & models.Q(customer__isnull=True))
                    | (models.Q(agent__isnull=True) & models.Q(customer__isnull=False))
                ),
                name="otp_codes_exactly_one_subject",
            )
        ]
