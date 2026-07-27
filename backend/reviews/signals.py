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


@receiver(post_save, sender=Review, dispatch_uid="reviews.revalidate_on_save")
def revalidate_on_save(sender, instance: Review, **kwargs):
    if not instance.slug:
        return  # still a draft, never rendered publicly
    paths = ["/", f"/reviews/{instance.slug}"]
    transaction.on_commit(lambda: revalidate(paths))
