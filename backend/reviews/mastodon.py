"""Mastodon syndication (Decision 9).

Posting is a separate, manual act from publishing: a review can be corrected quietly
right up until the moment it federates, and after that it cannot be recalled. The one
invariant is that a review is posted at most once, ever.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

log = logging.getLogger(__name__)

# Every link counts as this many characters regardless of its real length, because
# Mastodon substitutes a fixed-width placeholder when measuring.
LINK_WEIGHT = 23


class MastodonError(RuntimeError):
    """Any failure talking to the instance."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class MastodonAuthError(MastodonError):
    """401/403. The token is wrong, expired, or lacks `write:statuses`."""


def configured() -> bool:
    return bool(settings.MASTODON_BASE_URL and settings.MASTODON_TOKEN)


def _truncate(text: str, budget: int) -> str:
    """Cut on a word boundary and mark it, so a sentence never stops mid-word."""
    if budget <= 1 or len(text) <= budget:
        return text[:budget] if len(text) > budget else text
    cut = text[: budget - 1]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return f"{cut.rstrip()}…"


def compose_status(review, url: str, *, max_chars: int | None = None,
                   hashtags: list[str] | None = None) -> str:
    """Build the toot.

    Priority when it does not fit: the link and the hashtags are never sacrificed --
    the link is the entire point of posting, and the hashtags are what give it reach.
    The summary is trimmed first, then the header.
    """
    max_chars = max_chars or settings.MASTODON_MAX_CHARS
    tags = " ".join(f"#{t.lstrip('#')}" for t in (hashtags or settings.MASTODON_HASHTAGS))

    book = review.book
    header = f"{book.title} — {book.authors}" if book.authors else book.title
    header = f"{header} · {review.stars_overall:g}/5"

    # Fixed cost: link, hashtags, and the blank lines between the three blocks.
    fixed = LINK_WEIGHT + len(tags) + len("\n\n") * 3
    remaining = max_chars - fixed
    if remaining < 0:
        # Nothing but the link and tags will fit. Post that rather than nothing.
        return f"{url}\n\n{tags}"

    header = _truncate(header, min(len(header), max(remaining - 20, 0)) or remaining)
    # `card_description`, not `summary`: a rating-only review would otherwise post a
    # bare title and a link. The fallback deliberately omits the title, so it does not
    # repeat the header.
    body = _truncate(review.card_description, max(remaining - len(header) - 1, 0))

    parts = [p for p in (header, body) if p]
    return "\n\n".join([*parts, url, tags])


def post_status(text: str, *, idempotency_key: str) -> dict:
    """Publish a status. Returns the created status object.

    `Idempotency-Key` is the guard against the nastiest failure here: the POST
    succeeds, the response is lost to a timeout, django-q2 retries, and the review
    federates twice. Mastodon returns the original status for a repeated key instead
    of creating a second one.
    """
    if not configured():
        raise MastodonError("MASTODON_BASE_URL/MASTODON_TOKEN are not set.")

    base = settings.MASTODON_BASE_URL.rstrip("/")
    if not base.startswith("https://"):
        # The token rides on this request; plaintext would hand it to the network.
        raise MastodonError(f"MASTODON_BASE_URL must be https://, got {base!r}")

    try:
        resp = requests.post(
            f"{base}/api/v1/statuses",
            headers={
                "Authorization": f"Bearer {settings.MASTODON_TOKEN}",
                "Idempotency-Key": idempotency_key,
            },
            data={"status": text, "visibility": settings.MASTODON_VISIBILITY},
            timeout=settings.MASTODON_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise MastodonError(f"POST /api/v1/statuses failed: {exc}") from exc

    if resp.status_code in (401, 403):
        raise MastodonAuthError(
            f"Mastodon rejected the token ({resp.status_code}). It must carry the "
            "write:statuses scope.",
            status=resp.status_code,
        )
    if not resp.ok:
        raise MastodonError(
            f"POST /api/v1/statuses returned {resp.status_code}: {resp.text[:200]}",
            status=resp.status_code,
        )

    status = resp.json()
    if not status.get("id"):
        raise MastodonError("Mastodon returned no status id; refusing to mark as posted.")
    return status
