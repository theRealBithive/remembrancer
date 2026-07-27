from django.core.management.base import BaseCommand, CommandError

from catalog.abs import AbsAuthError, AbsError
from catalog.sync import sync


class Command(BaseCommand):
    help = "Mirror the Audiobookshelf library and listening progress into the local catalog."

    def handle(self, *args, **options):
        try:
            report = sync()
        except AbsAuthError as exc:
            # Deliberately fatal and noisy. A swallowed 401 leaves the finished-book
            # queue permanently empty while every run still looks like a success.
            raise CommandError(f"Audiobookshelf authentication failed: {exc}") from exc
        except AbsError as exc:
            raise CommandError(f"Audiobookshelf sync failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"sync_abs: {report}"))
        for problem in report.cover_errors:
            self.stdout.write(self.style.WARNING(f"  cover: {problem}"))
