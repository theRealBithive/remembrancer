"""Read-only public API (django-ninja).

Consumed by Next.js server-side over the internal docker network during SSG/ISR --
never from the browser in P1. Caddy does route public /api/* here, so treat every
response as world-readable: only published reviews, and no admin-only fields.
"""

from __future__ import annotations

from django.conf import settings
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

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
    summary: str
    rating_overall: int
    rating_narration: int | None
    published_at: str | None
    book: BookOut


class ReviewOut(ReviewListOut):
    body_html: str
    view_count: int


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
        "rating_overall": review.rating_overall,
        "rating_narration": review.rating_narration,
        "published_at": review.published_at.isoformat() if review.published_at else None,
        "book": _book(review),
    }
    if full:
        data["body_html"] = review.body_html
        data["view_count"] = review.view_count
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
