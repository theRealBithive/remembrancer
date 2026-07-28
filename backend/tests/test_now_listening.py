"""The homepage's present tense: one in-progress book, and the year's shape.

Both features publish something the rest of the site does not. `current_book` puts a
book on a public page before any review exists, so the tests that matter most here are
the ones about what it *refuses* to show. `year_progress` publishes a calendar, so the
one that matters there is the year boundary -- 1 January in Europe/Berlin is still
December in UTC, and getting that wrong misfiles a book by a whole year.
"""

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from catalog.models import Book
from catalog.now import NOW_LISTENING_IDLE_DAYS, current_book, year_progress
from reviews.models import Review

pytestmark = pytest.mark.django_db


def in_progress(title, *, minutes_ago=10, progress=0.4, seconds=3600, **extra):
    """A book that qualifies, so each test can spoil exactly one thing about it."""
    fields = {
        "abs_item_id": f"abs-{title}",
        "title": title,
        "authors": "Someone",
        "duration_seconds": 12 * 3600,
        "is_finished": False,
        "progress": progress,
        "seconds_listened": seconds,
        "last_played_at": timezone.now() - timedelta(minutes=minutes_ago),
    }
    return Book.objects.create(**{**fields, **extra})


def finished_on(title, when: datetime, **extra):
    return Book.objects.create(
        abs_item_id=f"abs-{title}",
        title=title,
        is_finished=True,
        progress=1.0,
        finished_at=when,
        last_played_at=when,
        **extra,
    )


# -- one book, and only the right one ----------------------------------------

def test_three_books_on_the_go_yields_the_one_played_last():
    in_progress("Anathem", minutes_ago=600)
    latest = in_progress("Piranesi", minutes_ago=5)
    in_progress("Dune", minutes_ago=90)

    assert current_book() == latest


def test_nothing_in_progress_is_a_normal_answer():
    finished_on("Dune", timezone.now())

    assert current_book() is None


@pytest.mark.parametrize(
    ("label", "spoiler"),
    [
        ("finished", {"is_finished": True}),
        ("gone from the library", {"is_orphaned": True}),
        ("hidden by hand", {"hide_from_public": True}),
        # Under the five-minute floor: opened once and closed is a mis-tap, and
        # announcing it as what you are reading would be a lie told by a threshold.
        ("barely opened", {"seconds": 120}),
        ("never actually started", {"progress": 0.0}),
    ],
)
def test_a_book_that_is_not_current_is_not_shown(label, spoiler):
    in_progress("Candidate", **spoiler)

    assert current_book() is None, label


def test_a_book_untouched_for_a_month_is_no_longer_current():
    """Well short of the 90 days that mark a book abandoned: "currently" is the
    stronger claim, and a book silent since last month is not it."""
    in_progress("Stalled", minutes_ago=(NOW_LISTENING_IDLE_DAYS + 1) * 24 * 60)

    assert current_book() is None


def test_hiding_a_book_falls_through_to_the_next_one():
    in_progress("Embarrassing", minutes_ago=1, hide_from_public=True)
    visible = in_progress("Anathem", minutes_ago=30)

    assert current_book() == visible


# -- the year --------------------------------------------------------------

def berlin(year, month, day, hour=12, minute=0):
    return timezone.make_aware(
        datetime(year, month, day, hour, minute), timezone.get_current_timezone()
    )


def test_months_are_counted_where_the_books_were_finished():
    this_year = timezone.localdate().year
    finished_on("A", berlin(this_year, 3, 4))
    finished_on("B", berlin(this_year, 3, 20))
    finished_on("C", berlin(this_year, 7, 1))

    result = year_progress()

    assert result["total"] == 3
    assert result["months"][2] == 2
    assert result["months"][6] == 1
    assert len(result["months"]) == 12
    assert result["year"] == this_year


def test_new_years_day_in_berlin_is_not_last_december():
    """Stored as 23:30 UTC on 31 December. A naive `finished_at__year` lookup files it
    under the wrong year on Postgres and the right one on SQLite, or the reverse --
    which is why the boundary is built explicitly in the site's own timezone."""
    this_year = timezone.localdate().year
    finished_on("Midnight", berlin(this_year, 1, 1, hour=0, minute=30))

    result = year_progress()

    assert result["months"][0] == 1
    assert result["total"] == 1


def test_last_years_reading_does_not_count_toward_this_year():
    this_year = timezone.localdate().year
    finished_on("Old", berlin(this_year - 1, 12, 31, hour=23, minute=30))

    assert year_progress()["total"] == 0


def test_a_hidden_book_still_counts():
    """The flag keeps a title off the page. A number reveals nothing, and a count that
    quietly disagreed with the library would be worse than no count at all."""
    finished_on("Hidden", berlin(timezone.localdate().year, 5, 5), hide_from_public=True)

    assert year_progress()["total"] == 1


def test_a_reviewed_book_counts_even_after_it_vanishes_upstream():
    """Same rule as the profile export: the file may be gone, but finishing it happened."""
    year = timezone.localdate().year
    orphan = finished_on("Gone", berlin(year, 2, 2), is_orphaned=True)
    Review.objects.create(book=orphan, rating_overall=8)
    finished_on("AlsoGone", berlin(year, 2, 3), is_orphaned=True)

    assert year_progress()["total"] == 1


def test_the_current_month_travels_with_the_counts():
    # The page is cached, so a browser in another timezone must not be the thing that
    # decides which bucket to highlight.
    assert year_progress()["month"] == timezone.localdate().month


# -- the endpoint ------------------------------------------------------------

def test_the_endpoint_publishes_no_dates(client):
    book = in_progress("Anathem")
    finished_on("Dune", berlin(timezone.localdate().year, 4, 1))

    payload = client.get("/api/now").json()

    assert set(payload) == {"listening", "year"}
    assert set(payload["listening"]) == {
        "title", "authors", "narrators", "cover_thumb_url", "duration_seconds", "progress",
    }
    assert set(payload["year"]) == {"year", "month", "total", "months"}
    assert payload["listening"]["title"] == book.title
    assert payload["year"]["total"] == 1


def test_the_endpoint_says_null_rather_than_omitting_the_book(client):
    payload = client.get("/api/now").json()

    assert payload["listening"] is None
    assert payload["year"]["total"] == 0
    assert payload["year"]["months"] == [0] * 12


def test_the_endpoint_takes_no_writes(client):
    for method in (client.post, client.put, client.delete):
        assert method("/api/now").status_code in (404, 405)
