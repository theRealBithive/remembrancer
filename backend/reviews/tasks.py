"""django-q2 entry points for syndication."""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from reviews.mastodon import compose_status, post_status
from reviews.models import Review

log = logging.getLogger(__name__)


def post_review_to_mastodon(review_pk: int) -> str:
    """Federate a published review, at most once ever.

    The guard lives *here*, not in the admin action, because django-q2 retries: a task
    that failed after posting would otherwise post again on the next attempt. It is
    taken under `select_for_update()` so two workers cannot both read "not yet posted"
    and both post.

    The row lock is held across an HTTP call, which is normally worth avoiding. It is
    acceptable here because the call is hard-bounded by MASTODON_TIMEOUT and the only
    contender for this row is another attempt at this same task -- which is exactly
    what must be serialised. `Idempotency-Key` covers the remaining hole, where the
    post succeeds but the response never arrives.
    """
    with transaction.atomic():
        review = Review.objects.select_for_update().select_related("book").get(pk=review_pk)

        if review.mastodon_status_id:
            log.info("Review %s already posted as %s", review_pk, review.mastodon_status_id)
            return f"already posted: {review.mastodon_status_id}"

        if not review.is_published or not review.slug:
            # A draft has no public URL, so a toot linking to it would 404 forever.
            raise ValueError(f"Review {review_pk} is not published; refusing to post.")

        url = f"{settings.SITE_URL.rstrip('/')}{review.get_absolute_path()}"
        status = post_status(
            compose_status(review, url),
            idempotency_key=f"remembrancer-review-{review.pk}",
        )

        review.mastodon_status_id = str(status["id"])
        review.mastodon_posted_at = timezone.now()
        review.save(update_fields=["mastodon_status_id", "mastodon_posted_at"])

    log.info("Posted review %s as %s", review_pk, status["id"])
    return status.get("url") or str(status["id"])
