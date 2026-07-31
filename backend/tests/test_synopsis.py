"""The synopsis: shown to a reader, withheld from every machine.

A synopsis is written by a model *from* my own review. That provenance is the whole
reason for these tests. On the page it is honest — collapsed, labelled, obviously not
mine. Anywhere the site speaks in my voice it would be a laundered echo: a
recommender reading it in the export would count one opinion twice and read the
repetition as corroboration, and a share card or a toot would put a paraphrase of my
words under my name.

So most of what follows asserts an absence. Each one guards a different surface that
already exists and already has a plausible reason to reach for this field.
"""

import pytest

from reviews.models import Review

pytestmark = pytest.mark.django_db

# Distinctive enough that finding it anywhere is unambiguous, and it appears nowhere
# else in the fixtures.
SENTINEL = "Grimlock the axolotl inherits a lighthouse"


@pytest.fixture
def synopsised(book):
    return Review.objects.create(
        book=book,
        rating_overall=9,
        summary="Ray Porter carries it.",
        body_markdown="A *lone* astronaut.",
        synopsis_markdown=f"{SENTINEL}, and the fog never lifts.",
        status=Review.Status.PUBLISHED,
    )


# -- the model ---------------------------------------------------------------


def test_a_review_carries_no_synopsis_by_default(book):
    """Most reviews will never have one. Empty has to be the quiet, renderable state."""
    review = Review.objects.create(book=book, rating_overall=8)

    assert review.synopsis_markdown == ""
    assert review.synopsis_html == ""


def test_it_is_rendered_through_the_same_sanitizer_as_the_body(book):
    review = Review.objects.create(
        book=book,
        rating_overall=8,
        synopsis_markdown="<script>alert(1)</script><details>fold</details>\n\n*shipwreck*",
    )

    html = review.synopsis_html

    assert "<script>" not in html
    # <details> is the page's own disclosure element. If it survived the allowlist,
    # pasted text could nest a second one inside the one wrapping it.
    assert "<details>" not in html
    assert "<em>shipwreck</em>" in html


# -- the public surfaces -----------------------------------------------------


def test_the_detail_api_ships_it_and_the_listing_does_not(client, synopsised):
    detail = client.get(f"/api/reviews/{synopsised.slug}").json()
    listing = client.get("/api/reviews").json()

    assert SENTINEL in detail["synopsis_html"]
    assert "synopsis_html" not in listing[0], "a card has no use for it"


def test_the_api_ships_an_empty_string_rather_than_omitting_it(client, book):
    Review.objects.create(book=book, rating_overall=6, status=Review.Status.PUBLISHED)
    review = Review.objects.get()

    # A missing key would make the page's `review.synopsis_html &&` undefined instead
    # of "" -- same rendering, but it would hide a real serialisation bug.
    detail = client.get(f"/api/reviews/{review.slug}").json()

    assert detail["synopsis_html"] == ""


def test_the_synopsis_never_becomes_the_share_card(book):
    """The one a future change would plausibly "fix".

    `card_description` exists precisely to fill a blank card, and a rating-only review
    with a synopsis sitting right there looks like the obvious fallback. It is not:
    that string becomes og:description and the toot, both of which speak as me.
    """
    review = Review.objects.create(
        book=book,
        rating_overall=8,
        summary="",
        body_markdown="",
        synopsis_markdown=SENTINEL,
        status=Review.Status.PUBLISHED,
    )

    assert review.card_description == "4 out of 5 stars"
    assert SENTINEL not in review.card_description


def test_the_feed_never_quotes_it(client, synopsised):
    body = client.get("/feed.xml").content.decode()

    assert "Project Hail Mary" in body, "the review itself is in the feed"
    assert SENTINEL not in body


def test_the_toot_never_quotes_it(synopsised):
    from reviews.mastodon import compose_status

    text = compose_status(
        synopsised,
        "https://remembrancer.test/reviews/phm",
        max_chars=500,
        hashtags=["bookstodon"],
    )

    assert SENTINEL not in text


# -- the export --------------------------------------------------------------


def test_the_export_never_quotes_it(synopsised):
    """The load-bearing one.

    The export is where a machine forms a view of my taste from my own words. A
    paraphrase of those words, arriving in the same document as if it were a second
    observation, is the exact false signal the format is built to avoid.
    """
    from catalog.profile import build_profile

    text = build_profile()

    assert "Ray Porter carries it." in text, "my own words are still exported"
    assert SENTINEL not in text
