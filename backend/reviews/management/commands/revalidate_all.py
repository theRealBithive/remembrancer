"""Rebuild every cached public page.

Two jobs:
  * post-deploy warm -- a fresh `next build` cannot reach Django, so the index page
    ships empty until something regenerates it;
  * recovery -- if the publish-time hook ever failed, this puts the cache right
    without waiting out the time-based revalidate.
"""

from django.core.management.base import BaseCommand, CommandError

from remembrancer.revalidate import revalidate
from reviews.api import published


class Command(BaseCommand):
    help = "Ask Next.js to regenerate the index and every published review page."

    def handle(self, *args, **options):
        slugs = list(published().values_list("slug", flat=True))
        # /legal renders per request, so it needs no warming; it stays in the list as
        # a cheap guard in case caching is ever reintroduced there.
        paths = ["/", "/legal"] + [f"/reviews/{slug}" for slug in slugs]

        if not revalidate(paths):
            raise CommandError(
                "Revalidation failed. Check REVALIDATE_SECRET matches on both services "
                "and that the next container is reachable."
            )

        self.stdout.write(self.style.SUCCESS(f"Revalidated {len(paths)} paths."))
