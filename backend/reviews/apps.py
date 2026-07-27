from django.apps import AppConfig


class ReviewsConfig(AppConfig):
    name = "reviews"
    verbose_name = "Reviews"

    def ready(self):
        from reviews import signals  # noqa: F401  (registers the revalidation receiver)
