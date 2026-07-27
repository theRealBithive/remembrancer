"""Real client address, behind the proxy.

Every request reaches Django from Caddy, so `REMOTE_ADDR` is the proxy's container
address on every single one. Anything keyed on it -- django-axes lockouts here, the
P3 view beacon's rate limit later -- collapses into one global bucket, which turns a
per-attacker limit into a trivial denial of service against the operator.
"""

from django.http import HttpRequest


def client_ip(request: HttpRequest) -> str | None:
    """Trust exactly one header, and only because Caddy overwrites it.

    `X-Real-IP` is set from `{remote_host}` -- the actual TCP peer -- replacing
    whatever the client sent, so it cannot be forged.

    Deliberately *not* `X-Forwarded-For`: Caddy appends to it rather than replacing
    it, so a request arriving with a forged XFF leaves attacker-controlled entries in
    the chain. Any leftmost read of that is a lockout-evasion primitive, and an
    offset-from-the-right read silently breaks the day a hop is added or removed.

    Falls back to `REMOTE_ADDR` for requests that never traversed the proxy.

    This trusts `X-Real-IP` unconditionally, which is only sound because port 8000 is
    unpublished and reachable solely on the docker network. Publishing it -- even
    briefly, for debugging -- lets anyone set their own throttling identity.
    """
    forwarded = request.META.get("HTTP_X_REAL_IP", "").strip()
    return forwarded or request.META.get("REMOTE_ADDR")
