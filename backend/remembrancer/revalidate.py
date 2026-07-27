"""On-demand ISR invalidation.

Lives at project level so both `reviews` (on publish/edit) and `catalog` (when a sync
changes a book that already has a published review) can call it without importing
each other.

The hook is reachable only on the internal docker network -- Caddy routes public
/api/* to Django, so Next can never own a public /api route. The HMAC is therefore
defence in depth rather than the sole control.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

import requests
from django.conf import settings

log = logging.getLogger(__name__)


def sign(body: bytes) -> str:
    return hmac.new(settings.REVALIDATE_SECRET.encode(), body, hashlib.sha256).hexdigest()


def revalidate(paths: list[str]) -> bool:
    """Ask Next.js to drop its cached render of `paths`.

    Never raises: a publish must not fail because the frontend is briefly down. The
    time-based `revalidate` in Next is the safety net, so the worst case is a page
    that is stale for up to an hour rather than a lost review.
    """
    if not paths:
        return True
    if not settings.REVALIDATE_SECRET:
        log.warning("REVALIDATE_SECRET unset; skipping revalidation of %s", paths)
        return False

    body = json.dumps({"paths": sorted(set(paths))}, separators=(",", ":")).encode()
    try:
        resp = requests.post(
            f"{settings.NEXT_INTERNAL_URL}/api/revalidate",
            data=body,
            headers={"Content-Type": "application/json", "X-Signature": sign(body)},
            timeout=settings.REVALIDATE_TIMEOUT,
        )
    except requests.RequestException as exc:
        log.warning("Revalidation of %s failed: %s", paths, exc)
        return False

    if not resp.ok:
        log.warning("Revalidation of %s returned %s", paths, resp.status_code)
        return False
    log.info("Revalidated %s", paths)
    return True
