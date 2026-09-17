"""Tests for the knowledge base and CSAT services, plus the public
(AllowAny) endpoints in front of them.

Both KB and CSAT are reachable with no token at all — that's the design (the
review's unguessable UUID is the whole access control), and it's also the pair
of endpoints that broke when JWTAuthentication used to raise on a stale token.
"""

from datetime import datetime, timezone

from django.test import TestCase
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.test import APITestCase

from apps.accounts.models import Agent, Customer
from apps.accounts.security import create_access_token
from apps.support import services
from apps.support.models import Faq, FaqStatus, FaqVisibility, Review
from apps.tickets import services as ticket_services
from apps.tickets.models import PriorityLevel, TicketSource, TicketStatus

KB_LIST_URL = "/api/v1/customer/kb/articles"
KB_POPULAR_URL = "/api/v1/customer/kb/articles/popular"


def make_article(
    question="How do I reset my password?",
    *,
    description="Click the reset link on the sign-in page.",
    status=FaqStatus.PUBLISHED,
    visibility=FaqVisibility.PUBLIC,
    view_count=0,
) -> Faq:
    return Faq.objects.create(
        question=question,
        description=description,
        category="account",
        status=status,
        visibility=visibility,
        view_count=view_count,
        published_at=datetime.now(timezone.utc),
    )


def make_resolved_ticket_review() -> Review:
    """Goes through the real resolve path — create_pending_review is only ever
    reached from update_ticket()'s RESOLVED branch."""
    customer = Customer.objects.create(email="customer@example.com")
    agent = Agent.objects.create(email="agent@example.com")
    ticket = ticket_services.create_ticket(
        subject="Billing question",
        customer_id=customer.id,
        priority=PriorityLevel.MEDIUM,
        ticket_type="question",
        source=TicketSource.PORTAL,
        group_id=None,
        agent_id=agent.id,
        initial_message="I was charged twice.",
    )
    ticket_services.update_ticket(ticket.id, status=TicketStatus.RESOLVED)
    return Review.objects.get(ticket=ticket)


class ArticleServiceTests(TestCase):
    def test_get_article_increments_view_count(self):
        article = make_article(view_count=4)

        returned = services.get_article(article.id)

        # Both the persisted row and the instance about to be serialized.
        self.assertEqual(returned.view_count, 5)
        article.refresh_from_db()
        self.assertEqual(article.view_count, 5)

    def test_repeated_views_keep_incrementing(self):
        article = make_article()

        for _ in range(3):
            services.get_article(article.id)

        article.refresh_from_db()
        self.assertEqual(article.view_count, 3)

    def test_get_article_404s_for_a_draft(self):
        article = make_article(status=FaqStatus.DRAFT)

        with self.assertRaises(NotFound):
            services.get_article(article.id)

    def test_get_article_404s_for_a_private_article(self):
        article = make_article(visibility=FaqVisibility.PRIVATE)

        with self.assertRaises(NotFound):
            services.get_article(article.id)

    def test_unreachable_article_view_count_is_untouched(self):
        article = make_article(status=FaqStatus.DRAFT, view_count=7)

        with self.assertRaises(NotFound):
            services.get_article(article.id)

        article.refresh_from_db()
        self.assertEqual(article.view_count, 7)

    def test_search_returns_only_published_public_articles(self):
        published = make_article("Published and public")
        make_article("Draft article", status=FaqStatus.DRAFT)
        make_article("Private article", visibility=FaqVisibility.PRIVATE)
        make_article("Draft and private", status=FaqStatus.DRAFT, visibility=FaqVisibility.PRIVATE)

        results = services.search_articles("")

        self.assertEqual([a.id for a in results], [published.id])

    def test_search_matches_question_and_description_case_insensitively(self):
        by_question = make_article("Refund policy", description="unrelated body")
        by_description = make_article("Something else", description="Our REFUND window is 30 days")
        make_article("Nothing relevant", description="nothing here")

        results = {a.id for a in services.search_articles("refund")}

        self.assertEqual(results, {by_question.id, by_description.id})

    def test_search_never_leaks_a_matching_draft(self):
        make_article("Refund policy draft", status=FaqStatus.DRAFT)

        self.assertEqual(list(services.search_articles("refund")), [])

    def test_popular_articles_are_ranked_by_view_count_and_limited(self):
        make_article("Least", view_count=1)
        most = make_article("Most", view_count=99)
        make_article("Hidden but popular", view_count=500, status=FaqStatus.DRAFT)

        results = list(services.popular_articles(limit=2))

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].id, most.id)


class ReviewServiceTests(TestCase):
    def setUp(self):
        self.review = make_resolved_ticket_review()

    def test_pending_review_starts_unsubmitted(self):
        self.assertIsNone(self.review.submitted_at)
        self.assertIsNone(self.review.score)

    def test_submit_review_records_score_comment_and_timestamp(self):
        submitted = services.submit_review(self.review.id, 4, "Quick and helpful")

        self.assertEqual(submitted.score, 4)
        self.assertEqual(submitted.comment, "Quick and helpful")
        self.assertIsNotNone(submitted.submitted_at)

    def test_submit_review_stores_an_empty_comment_as_null(self):
        submitted = services.submit_review(self.review.id, 5)

        self.assertIsNone(submitted.comment)

    def test_second_submission_is_rejected(self):
        services.submit_review(self.review.id, 5, "Great")

        with self.assertRaises(ValidationError):
            services.submit_review(self.review.id, 1, "Changed my mind")

        self.review.refresh_from_db()
        self.assertEqual(self.review.score, 5)
        self.assertEqual(self.review.comment, "Great")

    def test_unknown_review_is_not_found(self):
        with self.assertRaises(NotFound):
            services.get_review_or_404("00000000-0000-0000-0000-000000000000")


class PublicKbEndpointTests(APITestCase):
    def setUp(self):
        self.article = make_article()

    def test_list_is_reachable_with_no_token(self):
        response = self.client.get(KB_LIST_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([a["id"] for a in response.data], [str(self.article.id)])

    def test_list_is_reachable_with_a_stale_token(self):
        response = self.client.get(KB_LIST_URL, HTTP_AUTHORIZATION="Bearer stale.garbage.token")
        self.assertEqual(response.status_code, 200)

    def test_popular_is_reachable_with_no_token(self):
        response = self.client.get(KB_POPULAR_URL)
        self.assertEqual(response.status_code, 200)

    def test_detail_is_reachable_with_no_token_and_counts_the_view(self):
        response = self.client.get(f"{KB_LIST_URL}/{self.article.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["question"], self.article.question)
        self.article.refresh_from_db()
        self.assertEqual(self.article.view_count, 1)

    def test_detail_of_an_unpublished_article_is_404(self):
        draft = make_article("Draft", status=FaqStatus.DRAFT)

        response = self.client.get(f"{KB_LIST_URL}/{draft.id}")
        self.assertEqual(response.status_code, 404)


class PublicCsatEndpointTests(APITestCase):
    def setUp(self):
        self.review = make_resolved_ticket_review()
        self.url = f"/api/v1/customer/csat/{self.review.id}"

    def test_get_is_reachable_with_no_token(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["submitted"])
        self.assertEqual(response.data["ticket_no"], self.review.ticket.ticket_no)

    def test_get_is_reachable_with_a_stale_token(self):
        response = self.client.get(self.url, HTTP_AUTHORIZATION="Bearer expired.or.garbage")
        self.assertEqual(response.status_code, 200)

    def test_get_is_reachable_with_an_unrelated_valid_token(self):
        """A visitor signed in as some other customer must not be blocked —
        the review id is the access control, not the session."""
        stranger = Customer.objects.create(email="stranger@example.com")
        token = create_access_token(subject=str(stranger.id), role="customer")

        response = self.client.get(self.url, HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 200)

    def test_submit_with_no_token(self):
        response = self.client.post(self.url, {"score": 5, "comment": "Perfect"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["submitted"])
        self.review.refresh_from_db()
        self.assertEqual(self.review.score, 5)

    def test_second_submission_is_400(self):
        self.client.post(self.url, {"score": 5}, format="json")

        response = self.client.post(self.url, {"score": 1}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_out_of_range_score_is_400(self):
        for score in (0, 6):
            with self.subTest(score=score):
                response = self.client.post(self.url, {"score": score}, format="json")
                self.assertEqual(response.status_code, 400)

    def test_unknown_review_is_404(self):
        response = self.client.get("/api/v1/customer/csat/00000000-0000-0000-0000-000000000000")
        self.assertEqual(response.status_code, 404)
