from datetime import UTC, datetime

from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed, NotFound, ValidationError

from apps.accounts.models import Agent, Customer, OtpCode, OtpPurpose
from apps.accounts.security import (
    create_access_token,
    generate_otp,
    hash_otp,
    otp_expiry,
    verify_otp_hash,
    verify_password,
)


def agent_login(email: str, password: str) -> tuple[Agent, str]:
    """Password step. Returns (agent, plaintext_otp) — the view decides how
    much of that to expose (see the dev_otp caveat in the view)."""
    agent = Agent.objects.filter(email=email).first()
    if agent is None or agent.password_hash is None or not verify_password(password, agent.password_hash):
        # Same message for "no such agent" and "wrong password" — don't reveal which.
        raise AuthenticationFailed("Invalid email or password")

    code = generate_otp()
    OtpCode.objects.create(
        agent=agent,
        purpose=OtpPurpose.AGENT_LOGIN_VERIFICATION,
        code_hash=hash_otp(code),
        expires_at=otp_expiry(),
    )
    print(f"[DEV OTP] agent {agent.email} verification code: {code}")
    return agent, code


def _latest_pending_otp(*, purpose: str, agent_id=None, customer_id=None) -> OtpCode:
    qs = OtpCode.objects.filter(purpose=purpose, consumed_at__isnull=True).order_by("-created_at")
    qs = qs.filter(agent_id=agent_id) if agent_id else qs.filter(customer_id=customer_id)
    otp = qs.first()
    if otp is None:
        raise ValidationError("No pending verification — request a new code")
    if otp.expires_at < datetime.now(UTC):
        raise ValidationError("Code expired — request a new one")
    if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise ValidationError("Too many attempts — request a new code")
    return otp


def agent_verify_otp(agent_id, code: str) -> tuple[Agent, str]:
    otp = _latest_pending_otp(purpose=OtpPurpose.AGENT_LOGIN_VERIFICATION, agent_id=agent_id)
    if not verify_otp_hash(code, otp.code_hash):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        raise ValidationError("Incorrect code")

    otp.consumed_at = datetime.now(UTC)
    otp.save(update_fields=["consumed_at"])

    agent = Agent.objects.get(id=agent_id)
    token = create_access_token(subject=str(agent.id), role=agent.role)
    return agent, token


def customer_request_otp(email: str) -> tuple[Customer, str]:
    customer = Customer.objects.filter(email=email).first()
    if customer is None:
        # NOTE: reveals whether an email has an account (enumeration risk) —
        # acceptable for now, same caveat as the FastAPI version.
        raise NotFound("No account found with that email")

    code = generate_otp()
    OtpCode.objects.create(
        customer=customer,
        purpose=OtpPurpose.CUSTOMER_LOGIN,
        code_hash=hash_otp(code),
        expires_at=otp_expiry(),
    )
    print(f"[DEV OTP] customer {customer.email} login code: {code}")
    return customer, code


def customer_verify_otp(customer_id, code: str) -> str:
    otp = _latest_pending_otp(purpose=OtpPurpose.CUSTOMER_LOGIN, customer_id=customer_id)
    if not verify_otp_hash(code, otp.code_hash):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        raise ValidationError("Incorrect code")

    otp.consumed_at = datetime.now(UTC)
    otp.save(update_fields=["consumed_at"])

    return create_access_token(subject=str(customer_id), role="customer")


def guest_ticket_request_otp(email: str) -> tuple[Customer, str]:
    """PRD §13.1 revision: a guest submitting a ticket verifies email
    ownership inline via OTP instead of a full sign-in redirect — this is
    the anti-spam gate (a bot can't read the email), not an account login.
    get_or_create because, unlike customer_request_otp (an existing-account
    login), this is also how a brand-new customer's very first contact is
    recorded — email is already unique on Customer, so this is a safe upsert."""
    customer, _ = Customer.objects.get_or_create(email=email)

    code = generate_otp()
    OtpCode.objects.create(
        customer=customer,
        purpose=OtpPurpose.CUSTOMER_TICKET_SUBMISSION,
        code_hash=hash_otp(code),
        expires_at=otp_expiry(),
    )
    print(f"[DEV OTP] guest ticket submission for {customer.email}: {code}")
    return customer, code


def verify_guest_ticket_otp(email: str, code: str) -> Customer:
    """Verifies and consumes the code, returns the customer it belongs to.
    Doesn't issue a token — the ticket-creation caller does that once the
    ticket itself is safely created, so a token is never handed out for a
    ticket that didn't actually get created."""
    customer = Customer.objects.filter(email=email).first()
    if customer is None:
        raise ValidationError("No pending verification — request a new code")

    otp = _latest_pending_otp(purpose=OtpPurpose.CUSTOMER_TICKET_SUBMISSION, customer_id=customer.id)
    if not verify_otp_hash(code, otp.code_hash):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        raise ValidationError("Incorrect code")

    otp.consumed_at = datetime.now(UTC)
    otp.save(update_fields=["consumed_at"])
    return customer
