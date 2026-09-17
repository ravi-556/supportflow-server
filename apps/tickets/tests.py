"""Tests for apps.tickets.services (where all the ticket business logic lives)
plus the role gating and per-customer scoping of the endpoints in front of it.
"""

from django.test import TestCase
from rest_framework.test import APITestCase

from apps.accounts.models import Agent, AgentRole, Customer, Group
from apps.accounts.security import create_access_token
from apps.support.models import Review
from apps.tickets import services
from apps.tickets.models import (
    ActivityActionType,
    Message,
    MessageStatus,
    PriorityLevel,
    ReplyByRole,
    Ticket,
    TicketActivity,
    TicketSource,
    TicketStatus,
)

AGENT_TICKETS_URL = "/api/v1/agent/tickets"
CUSTOMER_TICKETS_URL = "/api/v1/customer/tickets"


def make_customer(email="customer@example.com") -> Customer:
    return Customer.objects.create(email=email, first_name="Cust", last_name="Omer")


def make_agent(email="agent@example.com", role=AgentRole.AGENT) -> Agent:
    return Agent.objects.create(email=email, role=role, first_name="Ada")


def open_ticket(customer, *, subject="Cannot log in", agent=None, group=None) -> Ticket:
    return services.create_ticket(
        subject=subject,
        customer_id=customer.id,
        priority=PriorityLevel.MEDIUM,
        ticket_type="question",
        source=TicketSource.PORTAL,
        group_id=group.id if group else None,
        agent_id=agent.id if agent else None,
        initial_message="It just spins forever.",
    )


class CreateTicketServiceTests(TestCase):
    def setUp(self):
        self.customer = make_customer()

    def test_creates_ticket_first_message_and_activity(self):
        ticket = open_ticket(self.customer)

        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(ticket.status, TicketStatus.OPEN)
        self.assertEqual(ticket.customer_id, self.customer.id)

        message = Message.objects.get(ticket=ticket)
        self.assertEqual(message.description, "It just spins forever.")
        self.assertEqual(message.reply_by, ReplyByRole.CUSTOMER)
        self.assertEqual(message.customer_id, self.customer.id)
        self.assertIsNone(message.agent_id)
        self.assertFalse(message.is_private)
        self.assertEqual(message.status, MessageStatus.SENT)

        activity = TicketActivity.objects.get(ticket=ticket)
        self.assertEqual(activity.action_type, ActivityActionType.TICKET_CREATED)

    def test_agent_sourced_ticket_opens_with_an_agent_message(self):
        agent = make_agent()
        ticket = services.create_ticket(
            subject="Proactive outreach",
            customer_id=self.customer.id,
            priority=PriorityLevel.LOW,
            ticket_type="question",
            source=TicketSource.AGENT,
            group_id=None,
            agent_id=agent.id,
            initial_message="Following up on your call.",
        )

        message = Message.objects.get(ticket=ticket)
        self.assertEqual(message.reply_by, ReplyByRole.AGENT)
        self.assertEqual(message.agent_id, agent.id)
        self.assertIsNone(message.customer_id)

    def test_ticket_no_is_assigned_from_the_sequence_and_is_unique(self):
        first = open_ticket(self.customer, subject="One")
        second = open_ticket(self.customer, subject="Two")

        self.assertIsNotNone(first.ticket_no)
        self.assertIsNotNone(second.ticket_no)
        self.assertNotEqual(first.ticket_no, second.ticket_no)
        self.assertGreater(second.ticket_no, first.ticket_no)

    def test_returned_ticket_is_select_related_for_display_fields(self):
        group = Group.objects.create(name="Billing")
        agent = make_agent()
        ticket = open_ticket(self.customer, agent=agent, group=group)

        # No extra queries: customer/agent/group were joined in by the re-fetch.
        with self.assertNumQueries(0):
            self.assertEqual(ticket.customer_email, self.customer.email)
            self.assertEqual(ticket.customer_name, "Cust Omer")
            self.assertEqual(ticket.agent_name, "Ada")
            self.assertEqual(ticket.group_name, "Billing")


class UpdateTicketServiceTests(TestCase):
    def setUp(self):
        self.customer = make_customer()
        self.agent = make_agent()
        self.ticket = open_ticket(self.customer)

    def _activity_types(self):
        return list(
            TicketActivity.objects.filter(ticket=self.ticket)
            .order_by("created_at")
            .values_list("action_type", flat=True)
        )

    def test_status_change_writes_a_status_change_activity(self):
        services.update_ticket(
            self.ticket.id, status=TicketStatus.CLOSED, changed_by_agent_id=self.agent.id
        )

        activity = TicketActivity.objects.get(
            ticket=self.ticket, action_type=ActivityActionType.STATUS_CHANGE
        )
        self.assertEqual(activity.status_change, "open -> closed")
        self.assertEqual(activity.agent_id, self.agent.id)

    def test_no_op_status_change_writes_no_activity(self):
        services.update_ticket(self.ticket.id, status=TicketStatus.OPEN)
        self.assertEqual(self._activity_types(), [ActivityActionType.TICKET_CREATED])

    def test_moving_into_pending_pauses_sla(self):
        services.update_ticket(self.ticket.id, status=TicketStatus.PENDING)

        self.assertIn(ActivityActionType.SLA_PAUSED, self._activity_types())
        self.assertNotIn(ActivityActionType.SLA_RESUMED, self._activity_types())

    def test_moving_out_of_pending_resumes_sla(self):
        services.update_ticket(self.ticket.id, status=TicketStatus.PENDING)
        services.update_ticket(self.ticket.id, status=TicketStatus.OPEN)

        self.assertIn(ActivityActionType.SLA_RESUMED, self._activity_types())

    def test_resolving_sets_resolved_at_and_creates_a_pending_review(self):
        ticket = services.update_ticket(self.ticket.id, status=TicketStatus.RESOLVED)

        self.assertEqual(ticket.status, TicketStatus.RESOLVED)
        self.assertIsNotNone(ticket.resolved_at)

        review = Review.objects.get(ticket=ticket)
        self.assertIsNone(review.submitted_at)
        self.assertIsNone(review.score)
        self.assertEqual(review.customer_id, self.customer.id)

    def test_re_resolving_does_not_create_a_second_review(self):
        services.update_ticket(self.ticket.id, status=TicketStatus.RESOLVED)
        services.update_ticket(self.ticket.id, status=TicketStatus.OPEN)
        services.update_ticket(self.ticket.id, status=TicketStatus.RESOLVED)

        self.assertEqual(Review.objects.filter(ticket=self.ticket).count(), 1)

    def test_closing_sets_closed_at(self):
        ticket = services.update_ticket(self.ticket.id, status=TicketStatus.CLOSED)

        self.assertIsNotNone(ticket.closed_at)
        self.assertIsNone(ticket.resolved_at)

    def test_priority_change_writes_a_priority_change_activity(self):
        services.update_ticket(self.ticket.id, priority=PriorityLevel.URGENT)

        activity = TicketActivity.objects.get(
            ticket=self.ticket, action_type=ActivityActionType.PRIORITY_CHANGE
        )
        self.assertEqual(activity.priority_change, "medium -> urgent")

    def test_assignment_change_writes_an_assignment_activity(self):
        ticket = services.update_ticket(self.ticket.id, agent_id=self.agent.id)

        self.assertEqual(ticket.agent_id, self.agent.id)
        self.assertEqual(
            TicketActivity.objects.filter(
                ticket=self.ticket, action_type=ActivityActionType.ASSIGNMENT_CHANGE
            ).count(),
            1,
        )

    def test_omitted_assignee_is_distinct_from_explicit_unassign(self):
        services.update_ticket(self.ticket.id, agent_id=self.agent.id)

        # Ellipsis sentinel = field absent from the PATCH: assignment untouched.
        untouched = services.update_ticket(self.ticket.id, status=TicketStatus.PENDING)
        self.assertEqual(untouched.agent_id, self.agent.id)

        # Explicit None = unassign.
        unassigned = services.update_ticket(self.ticket.id, agent_id=None)
        self.assertIsNone(unassigned.agent_id)


class CreateMessageServiceTests(TestCase):
    def setUp(self):
        self.customer = make_customer()
        self.agent = make_agent()
        self.ticket = open_ticket(self.customer)

    def _agent_reply(self, *, is_private=False):
        return services.create_message(
            self.ticket.id,
            description="Have you tried clearing your cookies?",
            reply_by=ReplyByRole.AGENT,
            customer_id=None,
            agent_id=self.agent.id,
            is_private=is_private,
            mentioned_agent_ids=[],
        )

    def _customer_reply(self):
        return services.create_message(
            self.ticket.id,
            description="Still broken.",
            reply_by=ReplyByRole.CUSTOMER,
            customer_id=self.customer.id,
            agent_id=None,
            is_private=False,
            mentioned_agent_ids=[],
        )

    def test_first_public_agent_reply_sets_first_responded_at(self):
        self.assertIsNone(self.ticket.first_responded_at)

        self._agent_reply()

        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.first_responded_at)

    def test_first_responded_at_is_not_overwritten_by_later_replies(self):
        self._agent_reply()
        self.ticket.refresh_from_db()
        first = self.ticket.first_responded_at

        self._agent_reply()
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.first_responded_at, first)

    def test_private_note_does_not_set_first_responded_at(self):
        message = self._agent_reply(is_private=True)

        self.assertTrue(message.is_private)
        self.assertIsNone(message.status)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.first_responded_at)

    def test_customer_reply_reopens_a_resolved_ticket_and_logs_it(self):
        services.update_ticket(self.ticket.id, status=TicketStatus.RESOLVED)

        self._customer_reply()

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.OPEN)
        reopen = TicketActivity.objects.filter(
            ticket=self.ticket, status_change="-> open (customer reply)"
        )
        self.assertEqual(reopen.count(), 1)
        self.assertEqual(reopen.get().action_type, ActivityActionType.STATUS_CHANGE)

    def test_customer_reply_reopens_a_pending_ticket(self):
        services.update_ticket(self.ticket.id, status=TicketStatus.PENDING)

        self._customer_reply()

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.OPEN)

    def test_customer_reply_on_an_open_ticket_logs_no_status_change(self):
        self._customer_reply()

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.OPEN)
        self.assertFalse(
            TicketActivity.objects.filter(
                ticket=self.ticket, action_type=ActivityActionType.STATUS_CHANGE
            ).exists()
        )

    def test_agent_reply_does_not_reopen_a_resolved_ticket(self):
        services.update_ticket(self.ticket.id, status=TicketStatus.RESOLVED)

        self._agent_reply()

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.RESOLVED)

    def test_mentions_are_recorded_against_the_private_note(self):
        mentioned = make_agent(email="colleague@example.com")
        message = services.create_message(
            self.ticket.id,
            description="@colleague can you look?",
            reply_by=ReplyByRole.AGENT,
            customer_id=None,
            agent_id=self.agent.id,
            is_private=True,
            mentioned_agent_ids=[mentioned.id],
        )

        mention = message.mentions.get()
        self.assertEqual(mention.mentioned_agent_id, mentioned.id)
        self.assertEqual(mention.mentioned_by_agent_id, self.agent.id)
        self.assertEqual(mention.ticket_id, self.ticket.id)


class CustomerTicketScopingServiceTests(TestCase):
    def setUp(self):
        self.customer = make_customer()
        self.other = make_customer(email="other@example.com")
        self.ticket = open_ticket(self.customer)

    def test_owner_can_fetch_their_own_ticket(self):
        found = services.get_customer_ticket_or_404(self.ticket.id, self.customer.id)
        self.assertEqual(found.id, self.ticket.id)

    def test_non_owner_gets_not_found_not_forbidden(self):
        from rest_framework.exceptions import NotFound

        with self.assertRaises(NotFound):
            services.get_customer_ticket_or_404(self.ticket.id, self.other.id)

    def test_customer_queryset_is_always_scoped(self):
        open_ticket(self.other, subject="Their problem")

        mine = services.customer_ticket_queryset(self.customer.id)
        self.assertEqual([t.id for t in mine], [self.ticket.id])

    def test_status_group_filters(self):
        resolved = open_ticket(self.customer, subject="Done")
        services.update_ticket(resolved.id, status=TicketStatus.RESOLVED)

        open_ids = {t.id for t in services.customer_ticket_queryset(self.customer.id, "open")}
        resolved_ids = {t.id for t in services.customer_ticket_queryset(self.customer.id, "resolved")}

        self.assertEqual(open_ids, {self.ticket.id})
        self.assertEqual(resolved_ids, {resolved.id})


class AgentTicketEndpointTests(APITestCase):
    def setUp(self):
        self.agent = make_agent()
        self.customer = make_customer()
        self.ticket = open_ticket(self.customer)
        self.agent_token = create_access_token(subject=str(self.agent.id), role=self.agent.role)
        self.customer_token = create_access_token(subject=str(self.customer.id), role="customer")

    def test_list_requires_a_token(self):
        response = self.client.get(AGENT_TICKETS_URL)
        self.assertEqual(response.status_code, 401)

    def test_list_rejects_a_customer_token_with_403(self):
        response = self.client.get(AGENT_TICKETS_URL, HTTP_AUTHORIZATION=f"Bearer {self.customer_token}")
        self.assertEqual(response.status_code, 403)

    def test_list_returns_tickets_for_an_agent(self):
        response = self.client.get(AGENT_TICKETS_URL, HTTP_AUTHORIZATION=f"Bearer {self.agent_token}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["ticket_no"], self.ticket.ticket_no)
        self.assertEqual(response.data[0]["customer_email"], self.customer.email)

    def test_list_status_filter(self):
        services.update_ticket(self.ticket.id, status=TicketStatus.CLOSED)

        response = self.client.get(
            f"{AGENT_TICKETS_URL}?status=open", HTTP_AUTHORIZATION=f"Bearer {self.agent_token}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_agent_can_see_any_customers_ticket(self):
        response = self.client.get(
            f"{AGENT_TICKETS_URL}/{self.ticket.id}", HTTP_AUTHORIZATION=f"Bearer {self.agent_token}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.ticket.id))

    def test_unknown_ticket_is_404(self):
        response = self.client.get(
            f"{AGENT_TICKETS_URL}/00000000-0000-0000-0000-000000000000",
            HTTP_AUTHORIZATION=f"Bearer {self.agent_token}",
        )
        self.assertEqual(response.status_code, 404)

    def test_patch_status_flows_through_the_service(self):
        response = self.client.patch(
            f"{AGENT_TICKETS_URL}/{self.ticket.id}",
            {"status": TicketStatus.RESOLVED, "changed_by_agent_id": str(self.agent.id)},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.agent_token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], TicketStatus.RESOLVED)
        # The service's side effects, not just the field write.
        self.assertTrue(Review.objects.filter(ticket=self.ticket).exists())
        self.assertIsNotNone(response.data["csat"])
        self.assertFalse(response.data["csat"]["submitted"])

    def test_private_note_is_visible_on_the_agent_thread(self):
        services.create_message(
            self.ticket.id,
            description="Internal: escalate to billing.",
            reply_by=ReplyByRole.AGENT,
            customer_id=None,
            agent_id=self.agent.id,
            is_private=True,
            mentioned_agent_ids=[],
        )

        response = self.client.get(
            f"{AGENT_TICKETS_URL}/{self.ticket.id}/messages",
            HTTP_AUTHORIZATION=f"Bearer {self.agent_token}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([m["is_private"] for m in response.data], [False, True])


class CustomerTicketEndpointTests(APITestCase):
    def setUp(self):
        self.customer = make_customer()
        self.other = make_customer(email="other@example.com")
        self.agent = make_agent()
        self.ticket = open_ticket(self.customer)
        self.other_ticket = open_ticket(self.other, subject="Their problem")
        self.token = create_access_token(subject=str(self.customer.id), role="customer")
        self.agent_token = create_access_token(subject=str(self.agent.id), role=self.agent.role)

    def test_list_requires_a_token(self):
        response = self.client.get(CUSTOMER_TICKETS_URL)
        self.assertEqual(response.status_code, 401)

    def test_list_rejects_an_agent_token_with_403(self):
        response = self.client.get(CUSTOMER_TICKETS_URL, HTTP_AUTHORIZATION=f"Bearer {self.agent_token}")
        self.assertEqual(response.status_code, 403)

    def test_list_only_returns_the_callers_own_tickets(self):
        response = self.client.get(CUSTOMER_TICKETS_URL, HTTP_AUTHORIZATION=f"Bearer {self.token}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([t["id"] for t in response.data], [str(self.ticket.id)])

    def test_another_customers_ticket_is_404_not_403(self):
        """PRD §13.3: a wrong owner must be indistinguishable from a
        nonexistent ticket — 403 would confirm the id exists."""
        response = self.client.get(
            f"{CUSTOMER_TICKETS_URL}/{self.other_ticket.id}", HTTP_AUTHORIZATION=f"Bearer {self.token}"
        )
        self.assertEqual(response.status_code, 404)

    def test_another_customers_thread_is_404(self):
        response = self.client.get(
            f"{CUSTOMER_TICKETS_URL}/{self.other_ticket.id}/messages",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(response.status_code, 404)

    def test_cannot_post_a_message_onto_another_customers_ticket(self):
        response = self.client.post(
            f"{CUSTOMER_TICKETS_URL}/{self.other_ticket.id}/messages",
            {"description": "Let me in"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Message.objects.filter(ticket=self.other_ticket).count(), 1)

    def test_thread_hides_private_notes(self):
        services.create_message(
            self.ticket.id,
            description="Internal only",
            reply_by=ReplyByRole.AGENT,
            customer_id=None,
            agent_id=self.agent.id,
            is_private=True,
            mentioned_agent_ids=[],
        )

        response = self.client.get(
            f"{CUSTOMER_TICKETS_URL}/{self.ticket.id}/messages", HTTP_AUTHORIZATION=f"Bearer {self.token}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertNotIn("Internal only", [m["description"] for m in response.data])
        # §8.2 visibility: never expose internal identifiers to the portal.
        self.assertNotIn("is_private", response.data[0])
        self.assertNotIn("agent_id", response.data[0])

    def test_creating_a_ticket_is_scoped_to_the_caller(self):
        response = self.client.post(
            CUSTOMER_TICKETS_URL,
            {"subject": "New issue", "description": "Details here", "ticket_type": "bug"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

        self.assertEqual(response.status_code, 201)
        created = Ticket.objects.get(id=response.data["id"])
        self.assertEqual(created.customer_id, self.customer.id)
        self.assertEqual(created.source, TicketSource.PORTAL)
        self.assertEqual(created.priority, PriorityLevel.MEDIUM)
