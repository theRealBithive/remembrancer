"""django-q2 entry points."""

import logging

from catalog.sync import sync

log = logging.getLogger(__name__)


def nightly_sync() -> str:
    """Scheduled mirror of the ABS library.

    Exceptions propagate on purpose: django-q2 marks the task failed and it becomes
    visible in the admin. Returning a string on failure would hide an expired token.
    """
    report = sync()
    log.info("nightly_sync: %s", report)
    return str(report)
