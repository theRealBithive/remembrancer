"""A rating on its own is a complete review.

The summary was mandatory because three things read it -- the page, the share card and
the toot -- and none of them had anything else to show. `Review.card_description` is
the single fallback they all go through now, so the field can be left empty without
any of them rendering a hole.
"""

import pytest

from reviews.models import Review

pytestmark = pytest.mark.django_db


@pytest.fixture
def stars_only(book):
    """The case the whole change exists for: I liked it, I have nothing to add."""
    return Review.objects.create(
        book=book, rating_overall=9, rating_narration=10, status=Review.Status.PUBLISHED
    )


# -- the fallback itself ------------------------------------------------------


def test_a_written_summary_wins(published_review):
    assert published_review.card_description == "Ray Porter carries an already excellent book."


def test_the_body_is_used_when_there_is_no_summary(stars_only):
    stars_only.body_markdown = "The **problem-solving** is the [plot](https://x.test)."

    described = stars_only.card_description

    assert described == "The problem-solving is the plot."
    assert "**" not in described and "http" not in described  # markdown, not syntax


def test_a_long_body_is_cut_at_a_sentence(stars_only):
    stars_only.body_markdown = "First sentence, quite short. " + "Then padding. " * 40

    described = stars_only.card_description

    assert len(described) <= 201
    assert described.endswith(".")
    assert " Then padding" in described  # not cut at the very first full stop


def test_a_body_with_no_sentence_end_is_cut_at_a_word(stars_only):
    stars_only.body_markdown = "word " * 100

    described = stars_only.card_description

    assert described.endswith("…")
    assert not described.endswith("wor…")  # never mid-word


def test_the_rating_speaks_for_itself_when_there_are_no_words(stars_only):
    assert stars_only.card_description == "4.5 out of 5 stars, narration 5"


def test_the_fallback_does_not_repeat_the_title(stars_only):
    """og:title and the toot header both carry it one line above."""
    assert stars_only.book.title not in stars_only.card_description


def test_narration_is_left_out_when_it_was_not_rated(stars_only):
    stars_only.rating_narration = None

    assert stars_only.card_description == "4.5 out of 5 stars"


# -- the four places that consume it ------------------------------------------


def test_a_review_without_a_summary_can_be_published(stars_only):
    """The invariant that used to be enforced by the field being required."""
    stars_only.refresh_from_db()

    assert stars_only.slug
    assert stars_only.is_published


def test_the_api_ships_both_the_raw_field_and_the_fallback(client, stars_only):
    data = client.get(f"/api/reviews/{stars_only.slug}").json()

    assert data["summary"] == ""  # what I wrote: nothing
    assert data["card_description"] == "4.5 out of 5 stars, narration 5"


def test_the_feed_item_is_never_empty(client, stars_only):
    body = client.get("/feed.xml").content.decode()

    assert "4.5 out of 5 stars, narration 5" in body


def test_the_toot_says_something_under_the_header(stars_only):
    from reviews.mastodon import compose_status

    status = compose_status(stars_only, "https://example.test/reviews/x", hashtags=[])

    assert "Project Hail Mary — Andy Weir · 4.5/5" in status
    assert "4.5 out of 5 stars, narration 5" in status
    # The header already named the book; saying it twice reads as a broken template.
    assert status.count("Project Hail Mary") == 1


def test_the_export_prints_the_rating_line_alone(stars_only):
    from catalog.profile import build_profile

    lines = build_profile().splitlines()

    assert any(line.startswith("4.5 stars | narration 5 |") for line in lines)
    # No bare "> " where the words would have been -- a quote marker quoting nothing.
    assert not [line for line in lines if line.startswith(">")]
