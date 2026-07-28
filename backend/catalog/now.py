"""What the homepage says about the present tense.

Two facts, both derived from the mirror rather than authored: the one book currently
being listened to, and how many were finished in each month of the current year.

Both publish more than the rest of the site does. Everywhere else a book only becomes
public when a review is written and published; `current_book` puts an *unreviewed* book
on the homepage the night it is started, which is why `Book.hide_from_public` exists.
And the monthly buckets are a calendar, which Decision 21 otherwise refuses -- a month
is coarse enough to read as a rhythm rather than a diary, and that is the whole of the
concession.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone

from catalog.models import ABANDONED_MIN_SECONDS, Book

# A book untouched for a month is not what you are listening to; it is one you have
# quietly stopped listening to. Well short of the 90 days that mark a book abandoned,
# because "currently" is a stronger claim than "not yet given up on".
NOW_LISTENING_IDLE_DAYS = 30

MONTHS_IN_YEAR = 12


def current_book() -> Book | None:
    """The single book ABS says was played most recently, or None.

    One book, never a list: `last_played_at` mirrors ABS's `lastUpdate`, so with three
    books on the go this returns whichever was touched last -- "currently" is what ABS
    thinks, not something the site infers.

    Shares the five-minute floor with `is_abandoned` deliberately. A book opened once
    and closed is a mis-tap, and announcing it as what you are reading would be a lie
    told by a threshold nobody chose.
    """
    return (
        Book.objects.filter(
            is_finished=False,
            is_orphaned=False,
            hide_from_public=False,
            progress__gt=0,
            seconds_listened__gte=ABANDONED_MIN_SECONDS,
            last_played_at__gte=timezone.now() - timedelta(days=NOW_LISTENING_IDLE_DAYS),
        )
        .order_by("-last_played_at")
        .first()
    )


def _year_bounds(year: int) -> tuple[datetime, datetime]:
    """1 January to 1 January, aware, in the site's own timezone.

    Explicit rather than `finished_at__year=`, which hands the conversion to the
    database: the suite runs on SQLite and production on Postgres, and they do not
    agree about it. With TIME_ZONE="Europe/Berlin" a book finished at 00:30 on New
    Year's Day is stored as 23:30 UTC on 31 December, so the boundary is exactly the
    thing that has to be got right.
    """
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime(year, 1, 1), tz)
    return start, timezone.make_aware(datetime(year + 1, 1, 1), tz)


def year_progress() -> dict:
    """Books finished this year, bucketed by the month they were finished in.

    `months` is always twelve entries, zero-filled, so the frontend can draw a full
    year without deciding what an absent month means.
    """
    today = timezone.localdate()
    start, end = _year_bounds(today.year)

    finished = (
        # The same "still in the library" rule the profile export uses: a reviewed book
        # counts even after it vanishes upstream, because finishing it still happened.
        Book.objects.filter(Q(is_orphaned=False) | Q(review__isnull=False))
        .filter(is_finished=True, finished_at__gte=start, finished_at__lt=end)
        .values_list("finished_at", flat=True)
    )

    months = [0] * MONTHS_IN_YEAR
    for finished_at in finished:
        months[timezone.localtime(finished_at).month - 1] += 1

    # `month` travels with the counts so the frontend can mark the month in progress
    # without consulting its own clock: the page is cached, and a browser in another
    # timezone would disagree with the buckets it is highlighting.
    return {
        "year": today.year,
        "month": today.month,
        "total": sum(months),
        "months": months,
    }
