"""Read-only public API (django-ninja).

Consumed by Next.js server-side over the internal docker network during SSG/ISR --
never from the browser in P1. Caddy does route public /api/* here, so treat every
response as world-readable: only published reviews, and no admin-only fields.
"""

from __future__ import annotations

from django.conf import settings
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError
from ninja.throttling import SimpleRateThrottle

from catalog.now import current_book, year_progress
from reviews.counting import record_view, visitor_key
from reviews.models import Review

api = NinjaAPI(
    title="Remembrancer",
    version="1.0",
    # The schema browser is a development convenience; it is not served publicly.
    docs_url="/docs" if settings.DEBUG else None,
)


def absolute(url: str | None) -> str | None:
    """Media URLs must be absolute: og:image is fetched by other servers."""
    if not url:
        return None
    return url if url.startswith("http") else f"{settings.SITE_URL}{url}"


class BookOut(Schema):
    title: str
    subtitle: str
    authors: str
    narrators: str
    series: str
    series_sequence: str
    published_year: int | None
    duration_seconds: int | None
    cover_url: str | None
    cover_thumb_url: str | None
    # How long it took relative to its length. Dates are deliberately absent: the pace
    # is the judgement, the calendar is private.
    days_to_finish: float | None
    listening_pace: float | None


class ReviewListOut(Schema):
    slug: str
    # `summary` is what was written and may be empty; `card_description` is what a
    # share card should say, with the fallback already applied. The frontend renders
    # the first and never has to reimplement the second.
    summary: str
    card_description: str
    rating_overall: int
    rating_narration: int | None
    published_at: str | None
    book: BookOut


class ReviewOut(ReviewListOut):
    body_html: str
    # Deliberately no view_count: this response is baked into an ISR page for up to an
    # hour, so any number here would be stale on arrival. The beacon returns the live
    # one instead.


class ViewOut(Schema):
    count: int


class NowListeningOut(Schema):
    """The book in progress. Note what is absent.

    No `started_at`, no `last_played_at`, no ABS id, no description. `progress` is the
    in-flight analogue of the pace published on a finished book -- a judgement rather
    than a calendar -- and Decision 21 refuses the timestamps that produced it.
    """

    title: str
    authors: str
    narrators: str
    cover_thumb_url: str | None
    duration_seconds: int | None
    progress: float


class YearProgressOut(Schema):
    year: int
    # 1..12, the month in progress on the server. Sent rather than inferred: the page
    # is cached, so the browser's clock is not the one that bucketed the counts.
    month: int
    total: int
    # Always twelve, zero-filled, January first.
    months: list[int]


class NowOut(Schema):
    # Singular and nullable on purpose: one book or none, and the schema is what makes
    # a list unrepresentable rather than a convention someone has to remember.
    listening: NowListeningOut | None
    year: YearProgressOut


def _book(review: Review) -> dict:
    b = review.book
    return {
        "title": b.title,
        "subtitle": b.subtitle,
        "authors": b.authors,
        "narrators": b.narrators,
        "series": b.series,
        "series_sequence": b.series_sequence,
        "published_year": b.published_year,
        "duration_seconds": b.duration_seconds,
        "cover_url": absolute(b.cover.url if b.cover else None),
        "cover_thumb_url": absolute(b.cover_thumb.url if b.cover_thumb else None),
        "days_to_finish": b.days_to_finish,
        "listening_pace": b.listening_pace,
    }


def _serialize(review: Review, *, full: bool) -> dict:
    data = {
        "slug": review.slug,
        "summary": review.summary,
        "card_description": review.card_description,
        "rating_overall": review.rating_overall,
        "rating_narration": review.rating_narration,
        "published_at": review.published_at.isoformat() if review.published_at else None,
        "book": _book(review),
    }
    if full:
        data["body_html"] = review.body_html
    return data


def published():
    return (
        Review.objects.filter(status=Review.Status.PUBLISHED, slug__isnull=False)
        .select_related("book")
        .order_by("-published_at")
    )


@api.get("/reviews", response=list[ReviewListOut], url_name="review_list")
def list_reviews(request):
    return [_serialize(r, full=False) for r in published()]


@api.get("/reviews/{slug}", response=ReviewOut, url_name="review_detail")
def get_review(request, slug: str):
    review = published().filter(slug=slug).first()
    if review is None:
        # Drafts are indistinguishable from nonexistent slugs from the outside.
        raise HttpError(404, "Not found")
    return _serialize(review, full=True)


@api.get("/now", response=NowOut, url_name="now")
def get_now(request):
    """What is being listened to, and the shape of the year so far.

    Unthrottled like the review endpoints: Next fetches this once per ISR window and
    serves the result from the static cache, so public traffic never arrives here.
    """
    book = current_book()
    return {
        "listening": book
        and {
            "title": book.title,
            "authors": book.authors,
            "narrators": book.narrators,
            "cover_thumb_url": absolute(book.cover_thumb.url if book.cover_thumb else None),
            "duration_seconds": book.duration_seconds,
            "progress": book.progress,
        },
        "year": year_progress(),
    }


class VisitorThrottle(SimpleRateThrottle):
    """Rate-limit the beacon per hashed visitor, not per proxy address.

    Keyed on the same hash the dedup uses, so it costs nothing extra and rotates with
    the salt. Without it the key would be Caddy's container address and one client
    would throttle the entire internet.
    """

    def get_cache_key(self, request):
        return f"throttle_view_{visitor_key(request)}"


@api.post(
    "/reviews/{slug}/view",
    response=ViewOut,
    url_name="review_view",
    throttle=[VisitorThrottle(rate=settings.VIEW_BEACON_RATE)],
)
def count_view(request, slug: str):
    """Count one view of a published review and return the running total.

    Called by the browser after hydration, which is what keeps the count honest for
    free: a Mastodon instance building a preview card fetches the HTML and never runs
    the script, so federation does not register as readership.

    This is a world-writable counter with no authentication, and it cannot be anything
    else without a cookie or a fingerprint -- both of which the design refuses. The
    throttle bounds the noise; it is not an integrity control. Treat the number as an
    indication of reach, never as evidence.
    """
    review = published().filter(slug=slug).first()
    if review is None:
        raise HttpError(404, "Not found")
    return {"count": record_view(review, visitor_key(request))}
