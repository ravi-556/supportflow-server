from datetime import datetime, timezone

from django.db import connection, transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound

# Cross-app service call, same kind of dependency apps/tickets/models.py
# already has on apps.accounts.models (Agent/Customer/Group) — just in a
# service function instead of a model import. apps.support doesn't import
# from apps.tickets (its Review.ticket FK uses a string reference), so this
# carries no circular-import risk.
from apps.support import services as support_services
from apps.tickets.models import (
    ActivityActionType,
    Mention,
    Message,
    MessageStatus,
    ReplyByRole,
    Ticket,
    TicketActivity,
    TicketStatus,
)

# PRD §8.3: "Pending pauses SLA by default" — the one status flagged
# pause-on-entry for v1. (Full per-status admin configurability is deferred.)
SLA_PAUSING_STATUSES = {TicketStatus.PENDING}


def ticket_queryset():
    """select_related so the *_name/*_email display properties on Ticket
    don't trigger N+1 queries — this is the Django equivalent of the
    joinedload() used in the FastAPI version."""
    return Ticket.objects.select_related("customer", "agent", "group")


def get_ticket_or_404(ticket_id) -> Ticket:
    ticket = ticket_queryset().filter(id=ticket_id).first()
    if ticket is None:
        raise NotFound("Ticket not found")
    return ticket


def get_customer_ticket_or_404(ticket_id, customer_id) -> Ticket:
    """PRD §13.3 — 404, not 403, on a mismatched owner: confirming a ticket
    ID exists to a customer who doesn't own it is its own small information
    leak, so a wrong owner must look identical to a nonexistent ticket.
    Every customer-facing per-ticket endpoint routes through this, never the
    bare get_ticket_or_404 the agent side uses."""
    ticket = get_ticket_or_404(ticket_id)
    if ticket.customer_id != customer_id:
        raise NotFound("Ticket not found")
    return ticket


def customer_ticket_queryset(customer_id, status_group=None):
    """PRD §13.2 — always scoped to customer_id server-side, unconditionally.
    Kept separate from the agent-facing ticket_queryset() caller so this
    mandatory scoping can never be accidentally skipped by a future
    customer-side caller."""
    qs = ticket_queryset().filter(customer_id=customer_id)
    if status_group == "open":
        qs = qs.filter(status__in=[TicketStatus.OPEN, TicketStatus.PENDING])
    elif status_group == "resolved":
        qs = qs.filter(status__in=[TicketStatus.RESOLVED, TicketStatus.CLOSED])
    return qs.order_by("-updated_at")


def _next_ticket_no() -> int:
    """Explicit, not relying on a Python-level model default — the column
    also has a DB-side default (see migrations/0002) as a safety net for any
    future direct-SQL insert, but application code always goes through here."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval('tickets_ticket_no_seq')")
        return cursor.fetchone()[0]


@transaction.atomic
def create_ticket(*, subject, customer_id, priority, ticket_type, source, group_id, agent_id, initial_message) -> Ticket:
    """PRD §3.1/§3.6: create the ticket, its first message, then (eventually)
    run create-time automation rules — automation execution is Phase 3, not
    built yet; this lays the ticket/message half of that flow."""
    ticket = Ticket.objects.create(
        ticket_no=_next_ticket_no(),
        subject=subject,
        customer_id=customer_id,
        priority=priority,
        ticket_type=ticket_type,
        source=source,
        group_id=group_id,
        agent_id=agent_id,
    )

    is_agent_initiated = source == "agent"
    Message.objects.create(
        ticket=ticket,
        description=initial_message,
        reply_by=ReplyByRole.AGENT if is_agent_initiated else ReplyByRole.CUSTOMER,
        agent_id=agent_id if is_agent_initiated else None,
        customer_id=None if is_agent_initiated else customer_id,
        is_private=False,
        status=MessageStatus.SENT,
    )

    TicketActivity.objects.create(ticket=ticket, action_type=ActivityActionType.TICKET_CREATED)

    return get_ticket_or_404(ticket.id)  # re-fetch with select_related for the response


@transaction.atomic
def update_ticket(ticket_id, *, status=None, priority=None, agent_id=..., group_id=..., changed_by_agent_id=None) -> Ticket:
    """PRD §5.2 A2 actions: Change Status / Change Priority / Change Assignee.
    Each field that actually changes writes its own ticket_activities row —
    the audit-trail requirement in PRD §8.4/§14. `agent_id`/`group_id` use
    `...` (Ellipsis) as the "not provided" sentinel so None (explicit
    unassign) is distinguishable from "field omitted from the PATCH".
    """
    ticket = get_ticket_or_404(ticket_id)
    now = datetime.now(timezone.utc)

    if status is not None and status != ticket.status:
        old_status, new_status = ticket.status, status
        ticket.status = new_status
        TicketActivity.objects.create(
            ticket=ticket,
            action_type=ActivityActionType.STATUS_CHANGE,
            agent_id=changed_by_agent_id,
            status_change=f"{old_status} -> {new_status}",
        )
        if new_status == TicketStatus.RESOLVED:
            ticket.resolved_at = now
            # PRD §13.5: pending CSAT review created the moment a ticket
            # becomes Resolved (send-via-email trigger excluded this pass —
            # no email provider or job scheduler exists to hang a delay on).
            support_services.create_pending_review(ticket)
        elif new_status == TicketStatus.CLOSED:
            ticket.closed_at = now

        if new_status in SLA_PAUSING_STATUSES and old_status not in SLA_PAUSING_STATUSES:
            TicketActivity.objects.create(
                ticket=ticket, action_type=ActivityActionType.SLA_PAUSED, agent_id=changed_by_agent_id
            )
        elif old_status in SLA_PAUSING_STATUSES and new_status not in SLA_PAUSING_STATUSES:
            TicketActivity.objects.create(
                ticket=ticket, action_type=ActivityActionType.SLA_RESUMED, agent_id=changed_by_agent_id
            )

    if priority is not None and priority != ticket.priority:
        old_priority = ticket.priority
        ticket.priority = priority
        TicketActivity.objects.create(
            ticket=ticket,
            action_type=ActivityActionType.PRIORITY_CHANGE,
            agent_id=changed_by_agent_id,
            priority_change=f"{old_priority} -> {priority}",
        )
        # NOTE: changing priority should re-select the matching SLA policy and
        # recompute *_sla_time. Not implemented yet — lands with the
        # automation engine in Phase 3, same as in the FastAPI version.

    if agent_id is not ... and agent_id != ticket.agent_id:
        ticket.agent_id = agent_id
        TicketActivity.objects.create(
            ticket=ticket, action_type=ActivityActionType.ASSIGNMENT_CHANGE, agent_id=changed_by_agent_id
        )

    if group_id is not ... and group_id != ticket.group_id:
        ticket.group_id = group_id
        TicketActivity.objects.create(
            ticket=ticket, action_type=ActivityActionType.ASSIGNMENT_CHANGE, agent_id=changed_by_agent_id
        )

    ticket.updated_at = now
    ticket.save()
    return get_ticket_or_404(ticket.id)


@transaction.atomic
def create_message(ticket_id, *, description, reply_by, customer_id, agent_id, is_private, mentioned_agent_ids) -> Message:
    """PRD §3.3/§3.5/§3.8/§4.2-4.3:
    - first public reply sets ticket.first_responded_at (first-response SLA fulfilled)
    - a customer reply on a Pending/Resolved/Closed ticket forces status back to Open
    - @mentions only ever apply to private notes, and only notify (via a Mention row)
    """
    ticket = get_object_or_404(Ticket, id=ticket_id)

    message = Message.objects.create(
        ticket=ticket,
        description=description,
        reply_by=reply_by,
        customer_id=customer_id,
        agent_id=agent_id,
        is_private=is_private,
        status=None if is_private else MessageStatus.SENT,
    )

    if not is_private and reply_by == ReplyByRole.AGENT and ticket.first_responded_at is None:
        ticket.first_responded_at = datetime.now(timezone.utc)
        ticket.save(update_fields=["first_responded_at"])

    if reply_by == ReplyByRole.CUSTOMER and ticket.status in (
        TicketStatus.PENDING,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    ):
        ticket.status = TicketStatus.OPEN
        ticket.save(update_fields=["status"])
        TicketActivity.objects.create(
            ticket=ticket,
            action_type=ActivityActionType.STATUS_CHANGE,
            status_change="-> open (customer reply)",
        )

    for mentioned_agent_id in mentioned_agent_ids or []:
        Mention.objects.create(
            ticket=ticket,
            message=message,
            mentioned_by_agent_id=agent_id,
            mentioned_agent_id=mentioned_agent_id,
        )

    return message
