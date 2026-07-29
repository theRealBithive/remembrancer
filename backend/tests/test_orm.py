"""The Orm mark: a second axis, not a sixth star.

Borrowed from Walter Moers. What these tests are really protecting is the *meaning*:
that it never gets inferred from the rating, that its absence is silence rather than a
verdict, and that the LLM export explains it rather than shipping a bare token no
model has ever seen in this sense.
"""

import pytest

from reviews.models import Review

pytestmark = pytest.mark.django_db


@pytest.fixture
def ormig(book):
    return Review.objects.create(
        book=book,
        rating_overall=9,
        rating_narration=10,
        had_orm=True,
        summary="Ray Porter carries it.",
        status=Review.Status.PUBLISHED,
    )


def test_a_review_claims_nothing_until_the_box_is_ticked(book):
    """Setting it is the whole act. The default has to be the quiet one, because every
    review ever written gets it retroactively."""
    review = Review.objects.create(book=book, rating_overall=10)

    assert review.had_orm is False


def test_a_perfect_rating_does_not_confer_it(book):
    review = Review.objects.create(book=book, rating_overall=10, had_orm=False)

    assert review.stars_overall == 5
    assert review.had_orm is False, "five stars is craft; Orm is a different claim"


# -- the public surfaces -----------------------------------------------------

def test_the_api_carries_the_mark(client, ormig):
    detail = client.get(f"/api/reviews/{ormig.slug}").json()
    listing = client.get("/api/reviews").json()

    assert detail["had_orm"] is True
    assert listing[0]["had_orm"] is True


def test_the_api_says_false_rather_than_omitting_it(client, book):
    Review.objects.create(book=book, rating_overall=6, status=Review.Status.PUBLISHED)

    # A missing key would make the frontend's `review.had_orm &&` silently undefined
    # instead of false -- same rendering, but it would hide a real serialisation bug.
    assert client.get("/api/reviews").json()[0]["had_orm"] is False


def test_the_feed_spells_the_word_out(client, ormig):
    """A reader shows the title as plain text with no page around it, so a glyph or an
    asterisk would arrive as an unexplained mark."""
    body = client.get("/feed.xml").content.decode()

    assert "Orm" in body
    assert f"{ormig.stars_overall:g}★, Orm" in body


# -- the export --------------------------------------------------------------

def test_the_export_explains_what_the_word_means(ormig):
    """The point of the export is that a model can read it cold. "ORM" alone is a
    token no model has met in this sense, and it would be read as the database kind."""
    from catalog.profile import build_profile

    text = build_profile()

    assert "Walter Moers" in text
    assert "not a sixth star" in text.lower() or "NOT a sixth star" in text
    # It has to say which way to weigh it, or it is just another field.
    assert "strongest positive signal" in text


def test_the_export_marks_the_book_next_to_its_rating(ormig):
    from catalog.profile import build_profile

    line = next(
        line for line in build_profile().splitlines() if line.startswith("4.5 stars")
    )

    assert line.startswith("4.5 stars | ORM |"), line


def test_the_export_stays_silent_about_the_unmarked(book):
    """Absence is not a complaint, so nothing is printed for it -- and a line saying
    "no orm" on four hundred books would cost real context to say nothing."""
    from catalog.profile import build_profile

    Review.objects.create(book=book, rating_overall=8, status=Review.Status.PUBLISHED)
    lines = build_profile().splitlines()

    assert not [line for line in lines if "ORM" in line and line.startswith("4 stars")]
