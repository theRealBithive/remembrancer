"""Same export as the admin button, for when you would rather pipe it."""

from django.core.management.base import BaseCommand

from catalog.profile import build_profile


class Command(BaseCommand):
    help = "Print the listening profile as LLM-readable text."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-unstarted",
            action="store_true",
            help="Omit the to-read pile. Much smaller, but the recommender can then "
            "suggest something already sitting in the library.",
        )

    def handle(self, *args, **options):
        # Straight to stdout, no styling: this output is meant to be redirected.
        self.stdout.write(build_profile(include_unstarted=not options["no_unstarted"]))
