"""Boot-time guards.

Local development and the test suite run on placeholder secrets so nothing has to be
exported by hand. That convenience is only safe if it cannot survive into production,
which is what these checks enforce: with DEBUG off, a forgotten value is a hard error
at startup rather than a quietly insecure deployment.
"""

from django.conf import settings
from django.core.checks import Error, Warning, register


def _is_placeholder(value: str) -> bool:
    """Catch the values shipped in `.env.example`, not just the settings default.

    The README's first-run path is `cp .env.example .env`. Matching only the default
    constant would let a deployment that skipped two lines boot with secrets that are
    published in this repository -- forgeable admin sessions and a forgeable
    revalidation hook. The guard has to recognise what the example file actually says.
    """
    return value.startswith(("change-me", settings.INSECURE_PLACEHOLDER))


@register(deploy=True)
def check_production_secrets(app_configs, **kwargs):
    problems = []

    if settings.DEBUG:
        # Same convention as Django's own deploy checks: a development box is allowed
        # to run on placeholders. This is what makes it safe to gate container
        # startup on `check --deploy` without breaking local runs.
        return problems

    if _is_placeholder(settings.SECRET_KEY) or len(settings.SECRET_KEY) < 50:
        problems.append(
            Error(
                "DJANGO_SECRET_KEY is a placeholder or too short to be a real key.",
                hint="Generate one: python -c \"import secrets; print(secrets.token_urlsafe(64))\"",
                id="remembrancer.E001",
            )
        )

    if not settings.REVALIDATE_SECRET or _is_placeholder(settings.REVALIDATE_SECRET):
        problems.append(
            Error(
                "REVALIDATE_SECRET is unset or still a placeholder.",
                hint="Set it to the same value in the web and next services.",
                id="remembrancer.E002",
            )
        )

    if not settings.SITE_URL.startswith("https://"):
        problems.append(
            Error(
                f"SITE_URL is {settings.SITE_URL!r}, which leaves CSRF_TRUSTED_ORIGINS empty "
                "and makes admin login fail behind the proxy.",
                hint="Set SITE_URL to the public https:// origin, including the scheme.",
                id="remembrancer.E003",
            )
        )

    if settings.DATABASES["default"]["ENGINE"].endswith("sqlite3"):
        problems.append(
            Error(
                "Running on SQLite. Set DATABASE_URL to the Postgres service.",
                id="remembrancer.E004",
            )
        )

    if not settings.ABS_TOKEN or not settings.ABS_BASE_URL:
        problems.append(
            Warning(
                "ABS_BASE_URL/ABS_TOKEN unset; the nightly sync will fail on every run.",
                id="remembrancer.W001",
            )
        )

    if settings.ADMIN_PATH == "admin":
        problems.append(
            Warning(
                "Admin is on the default /admin/ path.",
                hint="Set DJANGO_ADMIN_PATH to something non-obvious to cut bot noise.",
                id="remembrancer.W002",
            )
        )

    return problems
