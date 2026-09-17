import uuid

from django.db import models


class FaqStatus(models.TextChoices):
    DRAFT = "draft"
    PUBLISHED = "published"


class FaqVisibility(models.TextChoices):
    PUBLIC = "public"
    PRIVATE = "private"


class Review(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.CASCADE, related_name="reviews")
    agent = models.ForeignKey(
        "accounts.Agent", null=True, blank=True, on_delete=models.SET_NULL, related_name="reviews"
    )
    customer = models.ForeignKey(
        "accounts.Customer", null=True, blank=True, on_delete=models.SET_NULL, related_name="reviews"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    # PRD §13.5 revision: graded 1-5 score (Freshdesk's model), not binary
    # Good/Bad — reverted to the FloatField this column already had before
    # CSAT was ever spec'd. Whole-number steps only (UI submits 1/2/3/4/5);
    # range validation lives in the serializer, not the column type.
    score = models.FloatField(null=True, blank=True)
    comment = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "reviews"


class Faq(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.CharField(max_length=500)
    description = models.TextField(null=True, blank=True)
    category = models.CharField(max_length=200, null=True, blank=True)
    status = models.CharField(max_length=20, choices=FaqStatus.choices, default=FaqStatus.DRAFT)
    visibility = models.CharField(max_length=20, choices=FaqVisibility.choices, default=FaqVisibility.PRIVATE)
    published_at = models.DateTimeField(null=True, blank=True)
    # "Popular articles" ranking signal — see PRD §13.1 note: most-viewed is
    # an assumption, Zendesk doesn't publish its actual ranking algorithm.
    view_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "accounts.Agent", null=True, blank=True, on_delete=models.SET_NULL, related_name="faqs"
    )

    class Meta:
        db_table = "faq"

    def __str__(self) -> str:
        return self.question
