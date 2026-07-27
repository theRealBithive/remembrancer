"""View counting without identifying anyone (Decision 10).

The whole design exists to make one promise true: nothing that could be tied back to a
visitor is ever written to disk. What is stored is a single integer per review per day.
Deduplication needs to recognise a repeat visit, so it hashes the address and user
agent -- but with a secret salt that is generated at random, kept only in the cache,
and rotated daily. Once it rotates, yesterday's hashes cannot be recomputed by anyone,
including us. `/legal` states this to visitors, which makes it a commitment rather
than an implementation detail.
"""

from __future__ import annotations

import hashlib
import secrets

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from remembrancer.client_ip import client_ip
from reviews.models import Review, ReviewViewDay

# How long one visitor's repeat requests for the same review stop counting.
DEDUP_TTL = 6 * 60 * 60

# Longer than a day on purpose. The date in the key is what rotates the salt; this is
# only a floor, and a TTL shorter than 24h would rotate mid-day and double-count.
SALT_TTL = 26 * 60 * 60


def daily_salt() -> str:
    """The rotating secret. Never persisted, never logged, never sent anywhere.

    `get_or_set` is add-then-get, so gunicorn workers racing on the first request of
    the day converge on one value instead of each minting their own.
    """
    key = f"viewsalt:{timezone.localdate().isoformat()}"
    return cache.get_or_set(key, lambda: secrets.token_hex(32), timeout=SALT_TTL)


def visitor_key(request) -> str:
    """A short hash of (salt, address, user agent). Meaningless after rotation."""
    raw = "|".join(
        (
            daily_salt(),
            client_ip(request) or "",
            request.META.get("HTTP_USER_AGENT", "")[:256],
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def record_view(review: Review, key: str) -> int:
    """Count one view unless this visitor already counted recently.

    Returns the review's total either way, so a repeat visit still gets a number to
    render rather than a special case the frontend has to handle.

    `cache.add` is the dedup: it only succeeds if the key is absent, which makes the
    check-and-claim atomic across workers. With Redis that is cluster-wide; on the
    LocMemCache fallback it is per-process, so a multi-worker deployment without
    REDIS_URL would over-count by roughly the worker count. That configuration is
    refused at boot for other reasons, but this is the subtler cost of it.
    """
    if not cache.add(f"view:{review.pk}:{key}", 1, timeout=DEDUP_TTL):
        return review.view_count

    today = timezone.localdate()

    # A queryset .update(), not review.save(). Going through Review.save() would widen
    # update_fields with slug/published_at/updated_at and fire the revalidate signal,
    # so every single view would invalidate the cached page it was counting -- turning
    # a read into a write storm. .update() emits no post_save at all.
    Review.objects.filter(pk=review.pk).update(view_count=F("view_count") + 1)

    updated = ReviewViewDay.objects.filter(review=review, date=today).update(
        count=F("count") + 1
    )
    if not updated:
        # First view of the day. Two workers can arrive here at once; the unique
        # constraint decides, and the loser retries as an increment.
        try:
            with transaction.atomic():
                ReviewViewDay.objects.create(review=review, date=today, count=1)
        except IntegrityError:
            ReviewViewDay.objects.filter(review=review, date=today).update(
                count=F("count") + 1
            )

    return review.view_count + 1
