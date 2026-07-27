from django.apps import AppConfig


class RemembrancerConfig(AppConfig):
    name = "remembrancer"
    verbose_name = "Remembrancer"

    def ready(self):
        from remembrancer import checks  # noqa: F401  (registers deploy-time guards)
