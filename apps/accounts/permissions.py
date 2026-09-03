from rest_framework.permissions import BasePermission

AGENT_ROLES = {"admin", "agent", "light_agent"}


class IsAgent(BasePermission):
    """Guards every agent/admin endpoint. A customer's JWT is a valid token
    but the wrong role — DRF surfaces that as 403, not 401 (they ARE
    authenticated, just not authorized for this resource)."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and getattr(user, "is_authenticated", False) and user.role in AGENT_ROLES)


class IsCustomer(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and getattr(user, "is_authenticated", False) and user.role == "customer")
