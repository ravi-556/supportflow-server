from rest_framework.throttling import AnonRateThrottle


class AuthRateThrottle(AnonRateThrottle):
    """Per-IP rate limit for the unauthenticated auth/OTP endpoints.

    Applied explicitly (``throttle_classes = [AuthRateThrottle]``) to the
    handful of ``AllowAny`` views that mint credentials — agent login, the
    OTP request/verify pairs, and guest ticket submission. There is
    deliberately no ``DEFAULT_THROTTLE_CLASSES`` in settings: normal
    authenticated agent/customer traffic (ticket lists, message polling)
    should not be rate limited by this.

    Rate lives under the ``"auth"`` scope in ``REST_FRAMEWORK
    ["DEFAULT_THROTTLE_RATES"]``. The cache key is scope + client IP, so all
    six views share one budget per IP — intentional: the request-OTP and
    verify-OTP halves of a flow are the same attack, and a shared counter
    stops an attacker from getting 10/min per endpoint by rotating between
    them.

    Counters live in Django's cache framework, which is the unconfigured
    default ``LocMemCache`` here — per-process and wiped on restart. That is
    good enough to blunt password/OTP brute forcing on a single-process dev
    or small deployment, but it is *not* shared across gunicorn workers; a
    real shared cache backend would be needed for that to hold cluster-wide.
    """

    scope = "auth"

    def get_cache_key(self, request, view):
        # AnonRateThrottle returns None (i.e. "don't throttle") as soon as
        # request.user.is_authenticated, which would let an attacker bypass
        # the limit on these AllowAny views by attaching any valid Bearer
        # token — including one minted from their own throwaway account.
        # These endpoints hand out credentials, so key on the client IP
        # unconditionally instead.
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
