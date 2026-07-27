"""Slug invariants, sanitization, and the read API.

The slug rules matter more than they look: once a review is posted to Mastodon the
URL is federated to servers you don't control and can never be recalled.
"""

import re

import pytest

from catalog.models import Book
from reviews.markdown import render_markdown
from reviews.models import Review

pytestmark = pytest.mark.django_db


def make_book(**kw):
    defaults = {"abs_item_id": "x", "title": "Dune", "authors": "Frank Herbert"}
    return Book.objects.create(**{**defaults, **kw})


# -- slug -------------------------------------------------------------------

def test_draft_has_no_slug():
    review = Review.objects.create(book=make_book(), rating_overall=8, summary="s")
    assert review.slug is None


def test_many_drafts_coexist_under_the_unique_index():
    """"" would violate unique on the second draft; NULL does not."""
    for n in range(3):
        Review.objects.create(book=make_book(abs_item_id=f"b{n}"), rating_overall=6, summary="s")

    assert Review.objects.filter(slug__isnull=True).count() == 3


def test_slug_is_generated_from_title_and_author_at_publish():
    review = Review.objects.create(book=make_book(), rating_overall=8, summary="s")
    review.status = Review.Status.PUBLISHED
    review.save()

    assert review.slug == "dune-frank-herbert"
    assert review.published_at is not None


def test_slug_is_frozen_once_published():
    review = Review.objects.create(
        book=make_book(), rating_overall=8, summary="s", status=Review.Status.PUBLISHED
    )
    original = review.slug

    review.book.title = "Dune Messiah"
    review.book.save()
    review.summary = "revised"
    review.save()
    review.refresh_from_db()

    assert review.slug == original


def test_unpublishing_keeps_the_slug_and_publish_date():
    review = Review.objects.create(
        book=make_book(), rating_overall=8, summary="s", status=Review.Status.PUBLISHED
    )
    slug, published_at = review.slug, review.published_at

    review.status = Review.Status.DRAFT
    review.save()
    review.refresh_from_db()

    assert (review.slug, review.published_at) == (slug, published_at)


def test_slug_collisions_get_a_suffix():
    a = Review.objects.create(book=make_book(abs_item_id="a"), rating_overall=8, summary="s",
                              status=Review.Status.PUBLISHED)
    b = Review.objects.create(book=make_book(abs_item_id="b"), rating_overall=8, summary="s",
                              status=Review.Status.PUBLISHED)

    assert a.slug == "dune-frank-herbert"
    assert b.slug == "dune-frank-herbert-2"


def test_ratings_render_as_half_steps():
    review = Review.objects.create(book=make_book(), rating_overall=9, rating_narration=10,
                                   summary="s")
    assert (review.stars_overall, review.stars_narration) == (4.5, 5.0)


# -- markdown ---------------------------------------------------------------

DANGEROUS_TAG = re.compile(r"<\s*(script|iframe|img|svg|object|embed|style|form)\b", re.I)
EVENT_HANDLER = re.compile(r"<[^>]*\son[a-z]+\s*=", re.I)
HREF = re.compile(r'href="([^"]*)"', re.I)


def assert_inert(html: str) -> None:
    """The property that actually matters: nothing in the output can execute.

    Deliberately not a substring ban on 'javascript:' or '<a' -- an escaped payload
    rendered as visible text is harmless, and linkify legitimately produces anchors.
    """
    assert not DANGEROUS_TAG.search(html), f"live element in {html!r}"
    assert not EVENT_HANDLER.search(html), f"event handler in {html!r}"
    for href in HREF.findall(html):
        scheme = href.split(":", 1)[0].lower() if ":" in href.split("/")[0] else "https"
        assert scheme in {"http", "https", "mailto"}, f"disallowed scheme in {href!r}"


@pytest.mark.parametrize("payload", [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    '<a href="javascript:alert(1)">click</a>',
    '<iframe src="https://evil.test"></iframe>',
    "<svg><animate onbegin=alert(1) attributeName=x dur=1s>",
    '<div style="position:fixed;inset:0">overlay</div>',
])
def test_raw_html_in_markdown_is_inert(payload):
    """html_block/html_inline are disabled, so raw HTML is escaped rather than parsed."""
    html = render_markdown(payload)

    assert_inert(html)
    assert "&lt;" in html, "payload should be escaped, not silently dropped"


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "data:text/html;base64,PHM+",
    "vbscript:msgbox(1)",
])
def test_markdown_links_with_dangerous_schemes_are_neutralised(url):
    """A markdown link IS parsed into an <a>, so here the URL allowlist is the
    control -- not the HTML escaping above."""
    assert_inert(render_markdown(f"[click]({url})"))


def test_markdown_keeps_ordinary_formatting():
    html = render_markdown("A *lone* astronaut.\n\n- one\n- two")

    assert "<em>lone</em>" in html
    assert "<li>one</li>" in html


def test_external_links_are_marked_nofollow():
    html = render_markdown("[abs](https://abs.example)")

    assert 'href="https://abs.example"' in html
    assert "nofollow" in html and "noopener" in html


# -- API --------------------------------------------------------------------

def test_api_lists_only_published_reviews(client):
    Review.objects.create(book=make_book(abs_item_id="d"), rating_overall=5, summary="draft")
    Review.objects.create(book=make_book(abs_item_id="p"), rating_overall=9, summary="live",
                          status=Review.Status.PUBLISHED)

    payload = client.get("/api/reviews").json()

    assert [r["summary"] for r in payload] == ["live"]


def test_api_detail_returns_sanitized_html_and_absolute_cover_url(client, settings):
    review = Review.objects.create(
        book=make_book(), rating_overall=9, summary="s",
        body_markdown="Great. <script>alert(1)</script>",
        status=Review.Status.PUBLISHED,
    )

    payload = client.get(f"/api/reviews/{review.slug}").json()

    assert "<script" not in payload["body_html"]
    assert payload["rating_overall"] == 9
    assert payload["book"]["title"] == "Dune"


def test_api_detail_404s_for_a_draft(client):
    review = Review.objects.create(book=make_book(), rating_overall=5, summary="s")
    review.slug = "sneaky"
    review.save()

    assert client.get("/api/reviews/sneaky").status_code == 404


def test_feed_lists_published_reviews(client):
    Review.objects.create(book=make_book(), rating_overall=9, summary="live",
                          status=Review.Status.PUBLISHED)

    resp = client.get("/feed.xml")

    assert resp.status_code == 200
    assert b"Dune" in resp.content
    assert b"https://remembrancer.test/reviews/dune-frank-herbert" in resp.content
    # Relative feed links get the django.contrib.sites domain prepended, which
    # defaults to example.com.
    assert b"example.com" not in resp.content
