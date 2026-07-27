"""The three behaviours the whole design leans on.

Re-match keeps a published review attached when ABS re-mints an item id; orphaning
never destroys a book a review points at; a 401 is fatal and visible.
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from catalog.abs import AbsAuthError, AbsError
from catalog.models import Book, normalize_match_key
from catalog.sync import _timestamp, sync
from reviews.models import Review
from tests.conftest import FakeAbsClient, abs_item

pytestmark = pytest.mark.django_db


def test_creates_books_with_flattened_metadata():
    report = sync(FakeAbsClient(items=[abs_item()]))

    assert report.created == 1
    book = Book.objects.get()
    assert book.title == "Project Hail Mary"
    assert book.authors == "Andy Weir"
    assert book.narrators == "Ray Porter"
    assert book.series == "Standalone"
    assert book.published_year == 2021
    assert book.duration_seconds == 57600
    assert book.cover and book.cover_thumb


def test_second_run_is_idempotent():
    client = FakeAbsClient(items=[abs_item()])
    sync(client)
    report = sync(client)

    assert Book.objects.count() == 1
    assert report.created == 0
    assert report.unchanged == 1
    # Cover fingerprint unchanged -> not re-downloaded.
    assert client.cover_calls == 1


def test_rematches_on_asin_when_abs_remints_the_item_id():
    """The scenario the whole re-match chain exists for."""
    sync(FakeAbsClient(items=[abs_item(item_id="old-uuid")]))
    book = Book.objects.get()
    review = Review.objects.create(
        book=book, rating_overall=8, summary="Good.", status=Review.Status.PUBLISHED
    )

    sync(FakeAbsClient(items=[abs_item(item_id="fresh-uuid")]))

    assert Book.objects.count() == 1, "re-added item must not create a duplicate book"
    book.refresh_from_db()
    review.refresh_from_db()
    assert book.abs_item_id == "fresh-uuid"
    assert review.book_id == book.pk, "published review stayed attached"


def test_rematches_on_isbn_when_asin_is_absent():
    sync(FakeAbsClient(items=[abs_item(item_id="old", asin="", isbn="9780593135204")]))
    sync(FakeAbsClient(items=[abs_item(item_id="new", asin="", isbn="9780593135204")]))

    assert Book.objects.count() == 1
    assert Book.objects.get().abs_item_id == "new"


def test_rematches_on_title_and_author_as_last_resort():
    sync(FakeAbsClient(items=[abs_item(item_id="old", asin="", isbn="")]))
    sync(FakeAbsClient(items=[abs_item(item_id="new", asin="", isbn="")]))

    assert Book.objects.count() == 1


def test_distinct_books_are_not_merged():
    sync(FakeAbsClient(items=[
        abs_item(item_id="a", title="Project Hail Mary", asin="A1"),
        abs_item(item_id="b", title="The Martian", asin="A2"),
    ]))
    assert Book.objects.count() == 2


def test_same_book_in_two_libraries_stays_two_rows():
    """A shared ASIN must not make the second item overwrite the first.

    The same title present in two ABS libraries arrives as two items with distinct
    UUIDs but identical metadata. Without the claimed-pk guard the asin branch of
    `Book.match` resolves both to one row and the second silently disappears.
    """
    items = [
        abs_item(item_id="lib-a-1", title="Project Hail Mary", asin="A1"),
        abs_item(item_id="lib-b-1", title="Project Hail Mary", asin="A1"),
    ]
    report = sync(FakeAbsClient(items=items))

    assert Book.objects.count() == 2, "the second library's copy was swallowed"
    assert report.created == 2
    assert set(Book.objects.values_list("abs_item_id", flat=True)) == {"lib-a-1", "lib-b-1"}

    # And it must be stable: a second run re-matches each on its own abs_item_id.
    again = sync(FakeAbsClient(items=items))
    assert Book.objects.count() == 2
    assert again.created == 0


def test_ambiguous_weak_key_does_not_attach_to_the_wrong_book():
    """Two editions share a match_key; a third sync must not silently pick one."""
    key = normalize_match_key("Dune", "Frank Herbert")
    Book.objects.create(abs_item_id="ed-1", title="Dune", authors="Frank Herbert", match_key=key)
    Book.objects.create(abs_item_id="ed-2", title="Dune", authors="Frank Herbert", match_key=key)

    sync(FakeAbsClient(items=[abs_item(item_id="ed-3", title="Dune", author="Frank Herbert",
                                       asin="", isbn="")]))

    assert Book.objects.count() == 3, "ambiguity must create a new row, not guess"


def test_missing_items_are_orphaned_never_deleted():
    sync(FakeAbsClient(items=[abs_item()]))
    book = Book.objects.get()
    Review.objects.create(book=book, rating_overall=7, summary="Fine.")

    report = sync(FakeAbsClient(items=[]))

    assert report.orphaned == 1
    book.refresh_from_db()
    assert book.is_orphaned is True
    assert Book.objects.count() == 1
    assert Review.objects.count() == 1


def test_returning_item_clears_the_orphan_flag():
    sync(FakeAbsClient(items=[abs_item()]))
    sync(FakeAbsClient(items=[]))
    sync(FakeAbsClient(items=[abs_item()]))

    assert Book.objects.get().is_orphaned is False


@pytest.mark.parametrize(
    "finished_at",
    [
        pytest.param(1783843200000, id="epoch-milliseconds"),   # what ABS actually sends
        pytest.param("2026-07-01T20:00:00Z", id="iso-string"),
    ],
)
def test_finished_progress_populates_the_queue(finished_at):
    """`finishedAt` arrives as an integer from a real instance.

    The suite originally only exercised the ISO form, so `parse_datetime` blew up with
    a TypeError on the first live sync: a non-string is still truthy, so it sailed past
    the `or ""` guard instead of being rejected.
    """
    client = FakeAbsClient(
        items=[abs_item()],
        progress={"item-1": {"libraryItemId": "item-1", "isFinished": True,
                             "finishedAt": finished_at}},
    )
    sync(client)

    book = Book.objects.get()
    assert book.is_finished is True
    assert book.finished_at is not None
    assert book.finished_at.year == 2026
    assert timezone.is_aware(book.finished_at)
    assert Book.objects.filter(is_finished=True, review__isnull=True).count() == 1


@pytest.mark.parametrize(
    ("value", "expected_year"),
    [
        (1783843200000, 2026),      # milliseconds
        (1783843200, 2026),         # seconds
        ("1783843200000", 2026),    # numeric string
        ("2026-07-01T20:00:00Z", 2026),
        ("2026-07-01 20:00:00", 2026),   # naive -> made aware, not dropped
        (None, None),
        ("", None),
        (0, None),
        ("not a date", None),
        ([], None),                 # never raise on an unexpected shape
    ],
)
def test_timestamp_accepts_every_shape_abs_emits(value, expected_year):
    result = _timestamp(value)

    if expected_year is None:
        assert result is None
    else:
        assert result.year == expected_year
        assert timezone.is_aware(result), "a naive datetime would raise on save"


def test_a_missing_cover_is_not_re_requested_every_night():
    """404 means ABS has no cover, which will still be true tomorrow.

    Retrying it forever means a library with coverless items logs the same warnings
    on every scheduled run, which trains you to ignore the sync output.
    """
    class NoCover(FakeAbsClient):
        def cover_bytes(self, item_id):
            self.cover_calls += 1
            raise AbsError("no cover", status=404)

    client = NoCover(items=[abs_item()])
    first = sync(client)
    second = sync(client)

    assert len(first.cover_errors) == 1
    assert second.cover_errors == [], "a known-absent cover must not be retried"
    assert client.cover_calls == 1


def test_a_transient_cover_failure_is_retried():
    """A 5xx is not evidence the cover is missing, so it must not be banked."""
    class Flaky(FakeAbsClient):
        def cover_bytes(self, item_id):
            self.cover_calls += 1
            if self.cover_calls == 1:
                raise AbsError("upstream hiccup", status=503)
            return self.cover, "image/jpeg"

    client = Flaky(items=[abs_item()])
    sync(client)
    sync(client)

    assert client.cover_calls == 2
    assert Book.objects.get().cover


def test_unquoted_numeric_metadata_does_not_crash_the_sync():
    """ABS does not consistently quote these. A first sync must not die on one."""
    item = abs_item()
    item["media"]["metadata"].update({"isbn": 9780593135204, "asin": 12345})
    item["media"]["metadata"]["series"] = [{"name": "Standalone", "sequence": 2}]
    item["media"]["duration"] = 57600.75

    sync(FakeAbsClient(items=[item]))

    book = Book.objects.get()
    assert book.isbn == "9780593135204"
    assert book.asin == "12345"
    assert book.series_sequence == "2"
    assert book.duration_seconds == 57600


def test_metadata_edits_upstream_overwrite_the_mirror():
    sync(FakeAbsClient(items=[abs_item()]))
    sync(FakeAbsClient(items=[abs_item(author="Andy Wier")]))  # typo fixed upstream

    assert Book.objects.get().authors == "Andy Wier"


def test_changed_cover_replaces_the_file_instead_of_orphaning_it(media_root):
    """Django's storage suffixes on collision, so a naive re-save leaks a file per
    cover change and the media volume grows without bound."""
    sync(FakeAbsClient(items=[abs_item(updated_at=1)]))
    sync(FakeAbsClient(items=[abs_item(updated_at=2)]))  # new fingerprint
    sync(FakeAbsClient(items=[abs_item(updated_at=3)]))

    files = list((media_root / "covers").glob("*.jpg"))
    assert len(files) == 1, f"orphaned cover files: {[f.name for f in files]}"
    assert Book.objects.get().cover.name == "covers/item-1.jpg"


def test_cover_failure_does_not_lose_the_book():
    class BadCover(FakeAbsClient):
        def cover_bytes(self, item_id):
            from catalog.abs import AbsError

            raise AbsError("415 text/html")

    report = sync(BadCover(items=[abs_item()]))

    assert Book.objects.count() == 1
    assert len(report.cover_errors) == 1


def test_auth_failure_is_fatal_and_visible(monkeypatch):
    def boom():
        raise AbsAuthError("token expired")

    monkeypatch.setattr("catalog.sync.AbsClient", lambda *a, **kw: boom())

    with pytest.raises(CommandError, match="authentication failed"):
        call_command("sync_abs")


# -- the listening record ----------------------------------------------------

def _progress(**over):
    base = {"libraryItemId": "item-1", "isFinished": False, "progress": 0.0,
            "currentTime": 0, "startedAt": None, "finishedAt": None, "lastUpdate": None}
    return {"item-1": base | over}


def test_pace_is_captured_from_progress():
    """A 16h book finished over 4 days -> 4 h/day. This is the rating hint."""
    start = timezone.now() - timedelta(days=14)
    client = FakeAbsClient(
        items=[abs_item()],  # 57600s = 16h
        progress=_progress(isFinished=True, progress=1.0, currentTime=57600,
                           startedAt=start.timestamp() * 1000,
                           finishedAt=(start + timedelta(days=4)).timestamp() * 1000,
                           lastUpdate=(start + timedelta(days=4)).timestamp() * 1000),
    )
    sync(client)

    book = Book.objects.get()
    assert book.days_to_finish == pytest.approx(4, abs=0.01)
    assert book.listening_pace == pytest.approx(4.0, abs=0.05)
    assert book.is_abandoned is False


def test_pace_is_none_rather_than_wrong_when_a_timestamp_is_missing():
    client = FakeAbsClient(
        items=[abs_item()],
        progress=_progress(isFinished=True, progress=1.0,
                           finishedAt=timezone.now().timestamp() * 1000),
    )
    sync(client)

    book = Book.objects.get()
    assert book.is_finished is True
    assert book.days_to_finish is None
    assert book.listening_pace is None


def test_a_same_day_binge_does_not_divide_by_zero():
    now = timezone.now()
    client = FakeAbsClient(
        items=[abs_item()],
        progress=_progress(isFinished=True, progress=1.0,
                           startedAt=now.timestamp() * 1000,
                           finishedAt=(now + timedelta(minutes=1)).timestamp() * 1000),
    )
    sync(client)

    assert Book.objects.get().listening_pace is not None


@pytest.mark.parametrize(
    ("over", "expected", "why"),
    [
        ({"currentTime": 1200, "progress": 0.04, "idle": 200}, True, "the real case"),
        ({"currentTime": 1200, "progress": 0.04, "idle": 10}, False, "still in progress"),
        ({"currentTime": 30, "progress": 0.001, "idle": 400}, False, "never begun"),
        ({"currentTime": 9000, "progress": 0.60, "idle": 400}, False, "got properly into it"),
    ],
)
def test_abandonment_needs_a_verdict_not_a_mis_tap(over, expected, why):
    idle = over.pop("idle")
    last = timezone.now() - timedelta(days=idle)
    client = FakeAbsClient(
        items=[abs_item()],
        progress=_progress(lastUpdate=last.timestamp() * 1000,
                           startedAt=(last - timedelta(days=1)).timestamp() * 1000, **over),
    )
    sync(client)

    assert Book.objects.get().is_abandoned is expected, why


def test_abandoned_queryset_matches_the_property():
    """Two definitions that drift would show one queue and a different flag per row."""
    long_ago = (timezone.now() - timedelta(days=200)).timestamp() * 1000
    sync(FakeAbsClient(
        items=[abs_item(item_id="dropped"), abs_item(item_id="read", asin="A2", title="Other")],
        progress={
            "dropped": {"libraryItemId": "dropped", "isFinished": False, "progress": 0.03,
                        "currentTime": 900, "lastUpdate": long_ago},
            "read": {"libraryItemId": "read", "isFinished": True, "progress": 1.0,
                     "currentTime": 57600, "lastUpdate": long_ago, "finishedAt": long_ago},
        },
    ))

    by_sql = set(Book.objects.filter(Book.abandoned_q()).values_list("abs_item_id", flat=True))
    by_property = {b.abs_item_id for b in Book.objects.all() if b.is_abandoned}

    assert by_sql == by_property == {"dropped"}
