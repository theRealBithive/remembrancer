"""Publish -> revalidate.

Fires after commit so Next never re-fetches a row the transaction later rolls back.
Any review that owns a slug triggers it, including one being unpublished: the index
and the detail page both need to stop showing it.
"""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from remembrancer.revalidate import revalidate
from reviews.models import Review

# Written by the syndication task only; none of it is rendered on a public page.
SYNDICATION_FIELDS = {"mastodon_status_id", "mastodon_posted_at"}

# `Review.save()` widens every partial update with these, so they arrive on the signal
# whether or not the caller asked for them. They cannot be evidence of a real edit.
BOOKKEEPING_FIELDS = {"slug", "published_at", "updated_at"}


@receiver(post_save, sender=Review, dispatch_uid="reviews.revalidate_on_save")
def revalidate_on_save(sender, instance: Review, update_fields=None, **kwargs):
    if not instance.slug:
        return  # still a draft, never rendered publicly
    if update_fields and set(update_fields) - BOOKKEEPING_FIELDS <= SYNDICATION_FIELDS:
        return  # recording that a toot went out changes nothing readers can see
    paths = ["/", f"/reviews/{instance.slug}"]
    transaction.on_commit(lambda: revalidate(paths))
