import uuid

from django.db import models


class AutomationRuleType(models.TextChoices):
    ON_TICKET_CREATED = "on_ticket_created"
    SCHEDULED = "scheduled"


class AutomationRule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    rule_type = models.CharField(max_length=30, choices=AutomationRuleType.choices)
    active = models.BooleanField(default=True)
    rule_order = models.IntegerField(default=0)
    schedule_interval_minutes = models.IntegerField(null=True, blank=True)
    conditions = models.JSONField(default=list)  # [{field, operator, value}]
    actions = models.JSONField(default=list)  # [{type, value}]
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "automation_rules"
        indexes = [models.Index(fields=["rule_type", "active"])]

    def __str__(self) -> str:
        return self.name


class CannedResponse(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    body = models.TextField()
    group = models.ForeignKey(
        "accounts.Group", null=True, blank=True, on_delete=models.SET_NULL, related_name="canned_responses"
    )
    created_by = models.ForeignKey(
        "accounts.Agent", null=True, blank=True, on_delete=models.SET_NULL, related_name="canned_responses"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "canned_responses"

    def __str__(self) -> str:
        return self.title
