from datetime import datetime, timezone

from django.db.models import F, Q
from rest_framework.exceptions import NotFound, ValidationError

from apps.support.models import Faq, FaqStatus, FaqVisibility, Review


def _published_public_queryset():
    return Faq.objects.filter(status=FaqStatus.PUBLISHED, visibility=FaqVisibility.PUBLIC)


def search_articles(query: str):
    qs = _published_public_queryset()
    if query:
        qs = qs.filter(Q(question__icontains=query) | Q(description__icontains=query))
    return qs.order_by("-published_at")


def popular_articles(limit: int = 6):
    return _published_public_queryset().order_by("-view_count")[:limit]


def get_article(article_id) -> Faq:
    article = _published_public_queryset().filter(id=article_id).first()
    if article is None:
        raise NotFound("Article not found")
    # Atomic F() increment so concurrent views don't lose updates, then
    # reflect it on the in-memory instance we're about to serialize.
    Faq.objects.filter(id=article_id).update(view_count=F("view_count") + 1)
    article.view_count += 1
    return article


def create_pending_review(ticket) -> Review:
    """PRD §13.5 — called from update_ticket()'s RESOLVED branch. get_or_create
    on `ticket` makes this idempotent across re-resolutions: a reopened-then-
    resolved-again ticket doesn't get a second pending review. `agent` is
    copied from ticket.agent at this exact moment — a point-in-time snapshot,
    not a live FK, since reassignment shouldn't retroactively change whose
    CSAT score it was."""
    review, _ = Review.objects.get_or_create(
        ticket=ticket, defaults={"agent": ticket.agent, "customer": ticket.customer}
    )
    return review


def get_review_or_404(review_id) -> Review:
    review = Review.objects.select_related("ticket").filter(id=review_id).first()
    if review is None:
        raise NotFound("Review not found")
    return review


def submit_review(review_id, score: float, comment: str = "") -> Review:
    review = get_review_or_404(review_id)
    if review.submitted_at is not None:
        raise ValidationError("This survey has already been submitted")
    review.score = score
    review.comment = comment or None
    review.submitted_at = datetime.now(timezone.utc)
    review.save(update_fields=["score", "comment", "submitted_at"])
    return review
