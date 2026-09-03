import uuid

import jwt
from rest_framework import authentication

from apps.accounts.security import decode_access_token


class Principal:
    """Stand-in for request.user — Agent/Customer are plain domain models,
    not Django's built-in auth User, so DRF's IsAuthenticated just needs
    something with `.is_authenticated`."""

    is_authenticated = True

    def __init__(self, subject_id: uuid.UUID, role: str) -> None:
        self.id = subject_id
        self.role = role


class JWTAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        header = request.headers.get("Authorization")
        if not header or not header.startswith("Bearer "):
            return None  # no credentials supplied — let permission classes decide (401 vs anonymous-ok)

        token = header.removeprefix("Bearer ").strip()
        try:
            payload = decode_access_token(token)
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            # Treat a bad/expired token the same as no token at all (return
            # None), not a hard AuthenticationFailed. Raising here would 401
            # an AllowAny view outright — DRF fires authentication before
            # permission checks, so an exception here bypasses AllowAny
            # entirely regardless of the view's permission_classes. A stale
            # token in localStorage (e.g. from days ago) would otherwise
            # break every public endpoint — first hit on §13.5's CSAT page,
            # which is the first view that must work for a signed-in-elsewhere
            # visitor. Protected endpoints are unaffected: with no successful
            # authenticator, DRF raises NotAuthenticated (401, same as
            # today) rather than PermissionDenied (403) — the valid-token/
            # wrong-role 403 distinction in IsAgent/IsCustomer is untouched.
            return None

        principal = Principal(subject_id=uuid.UUID(payload["sub"]), role=payload["role"])
        return (principal, token)

    def authenticate_header(self, request):
        # Without this, DRF's APIView.handle_exception silently downgrades
        # AuthenticationFailed/NotAuthenticated from 401 to 403 (it only keeps
        # 401 when some authenticator declares a WWW-Authenticate challenge).
        # Real "no/bad token" must stay 401 — 403 is reserved for "valid token,
        # wrong role" (see IsAgent/IsCustomer in permissions.py).
        return "Bearer"
