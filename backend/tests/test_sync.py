"""The three behaviours the whole design leans on.

Re-match keeps a published review attached when ABS re-mints an item id; orphaning
never destroys a book a review points at; a 401 is fatal and visible.
"""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from catalog.abs import AbsAuthError
from catalog.models import Book, normalize_match_key
from catalog.sync import sync
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


def test_finished_progress_populates_the_queue():
    client = FakeAbsClient(
        items=[abs_item()],
        progress={"item-1": {"libraryItemId": "item-1", "isFinished": True,
                             "finishedAt": "2026-07-01T20:00:00Z"}},
    )
    sync(client)

    book = Book.objects.get()
    assert book.is_finished is True
    assert book.finished_at is not None
    assert Book.objects.filter(is_finished=True, review__isnull=True).count() == 1


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
