"""The LLM export: right signal, no leaks, and small enough to paste."""

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from catalog.models import Book
from catalog.profile import build_profile, profile_stats
from reviews.models import Review

pytestmark = pytest.mark.django_db


@pytest.fixture
def library(db, book):
    """One of each state, so every section is exercised."""
    Review.objects.create(
        book=book,
        rating_overall=9,
        rating_narration=10,
        summary="Ray Porter carries an already excellent book.",
        body_markdown="The problem-solving is the plot.\n\nRocky is the best alien "
        "in years.",
        status=Review.Status.PUBLISHED,
    )
    book.is_finished = True
    book.duration_seconds = 57600
    book.published_year = 2021
    book.save()

    Book.objects.create(
        abs_item_id="fin", title="Dune", authors="Frank Herbert", is_finished=True,
        duration_seconds=75600, published_year=1965,
    )
    Book.objects.create(
        abs_item_id="drop", title="Infinite Jest", authors="David Foster Wallace",
        progress=0.04, seconds_listened=1800,
        last_played_at=timezone.now() - datetime.timedelta(days=200),
    )
    Book.objects.create(
        abs_item_id="wip", title="Ubik", authors="Philip K. Dick", progress=0.55,
    )
    Book.objects.create(abs_item_id="todo", title="Piranesi", authors="Susanna Clarke")
    # A few more, because the to-read pile being the bulk of the library is the whole
    # reason the compact export exists.
    Book.objects.bulk_create(
        Book(abs_item_id=f"todo{i}", title=f"Unread {i}", authors="Someone")
        for i in range(20)
    )
    return Book.objects.all()


def test_every_state_gets_its_own_section(library):
    text = build_profile()

    assert "== REVIEWED" in text
    assert "== FINISHED, NOT YET REVIEWED" in text
    assert "== ABANDONED" in text
    assert "== IN PROGRESS" in text
    assert "== UNSTARTED" in text


def test_a_review_carries_its_rating_and_its_words(library):
    text = build_profile()

    assert "4.5 stars | narration 5" in text
    assert "> Ray Porter carries an already excellent book." in text


def test_the_whole_review_is_exported_not_just_the_summary(library):
    """The summary is written for a Mastodon card. The reasons are in the body."""
    text = build_profile()

    assert "> The problem-solving is the plot." in text
    assert "> Rocky is the best alien in years." in text


def test_a_review_without_a_body_still_renders(db, book):
    """`body_markdown` is optional, and a stray "> " line would be noise."""
    Review.objects.create(
        book=book, rating_overall=6, summary="Fine.", status=Review.Status.PUBLISHED
    )

    assert "> Fine.\n" in build_profile()
    assert "> \n" not in build_profile()


def test_the_legend_explains_pace_because_the_number_is_meaningless_alone(library):
    text = build_profile()

    assert "hours of audio per calendar day" in text


def test_the_to_read_pile_can_be_dropped(library):
    full = build_profile()
    compact = build_profile(include_unstarted=False)

    assert "Piranesi" in full
    assert "Piranesi" not in compact
    assert "unstarted books in the library, omitted" in compact
    assert len(compact) < len(full)


def test_a_reviewed_book_survives_vanishing_from_audiobookshelf(library, book):
    """The verdict was mine. It still describes my taste after the file is gone."""
    book.is_orphaned = True
    book.save()

    assert book.title in build_profile()


def test_an_unreviewed_orphan_is_dropped(library):
    Book.objects.filter(abs_item_id="todo").update(is_orphaned=True)

    assert "Piranesi" not in build_profile()


# -- what the recommender was missing ----------------------------------------


def test_the_reader_is_named_where_i_heard_the_book(library, book):
    """It is an audiobook profile. A narrator is a reason to pick a book up and a
    reason to put one down, and the file could not say either."""
    Book.objects.filter(pk=book.pk).update(narrators="Ray Porter")

    text = build_profile()

    assert "— Andy Weir, read by Ray Porter" in text


def test_the_to_read_pile_does_not_name_readers(library):
    """267 of ~380 lines, all of them books I have never heard. Cutting the reader
    there is what pays for naming it everywhere it means something."""
    Book.objects.filter(abs_item_id="todo").update(narrators="Some Narrator")

    unstarted = build_profile().split("== UNSTARTED")[1]

    assert "Piranesi" in unstarted
    assert "Some Narrator" not in unstarted


def test_comfort_reading_is_marked_and_explained(library):
    Book.objects.filter(abs_item_id="fin").update(is_comfort_read=True)

    text = build_profile()
    line = next(line for line in text.splitlines() if "Dune" in line)

    assert "| comfort |" in line
    # The marker is useless without the instruction: pace lies on these rows, and a
    # recommender that averages them into the rest produces a taste matching nobody.
    assert "never average it together" in text


def test_a_reviewed_comfort_read_keeps_its_review_and_its_marker(library, book):
    """The review is real taste data wherever it came from, so the book stays in
    REVIEWED -- but it still says what it is."""
    Book.objects.filter(pk=book.pk).update(is_comfort_read=True)

    reviewed = build_profile().split("== FINISHED")[0]

    assert "comfort" in reviewed
    assert "> Rocky is the best alien in years." in reviewed


def test_finished_books_carry_the_month_they_were_finished(library, book):
    """Without a date there is no trajectory, and "what should I read next" is a
    question about direction."""
    when = timezone.now() - datetime.timedelta(days=40)
    Book.objects.filter(pk=book.pk).update(finished_at=when)

    assert f"finished {timezone.localtime(when):%Y-%m}" in build_profile()


def test_a_stalled_book_says_when_it_was_last_opened(library):
    """31 books "in progress" and several untouched for a year. Without this they are
    indistinguishable from the one I am actually reading."""
    when = timezone.now() - datetime.timedelta(days=300)
    Book.objects.filter(abs_item_id="wip").update(last_played_at=when)

    line = next(line for line in build_profile().splitlines() if "Ubik" in line)

    assert f"last touched {timezone.localtime(when):%Y-%m}" in line


def test_a_missing_date_is_omitted_rather_than_printed_as_a_question_mark(library):
    """Plenty of books have no finished_at upstream. One "?" per line is enough."""
    assert "finished ?" not in build_profile()
    assert "last touched ?" not in build_profile()


def test_an_abandoned_book_can_say_why(library):
    """Cryptonomicon at 3% and Finnegans Wake at 16 minutes look identical in the file
    and are completely different failures."""
    Book.objects.filter(abs_item_id="drop").update(
        abandoned_note="wrong moment, not the wrong book"
    )

    text = build_profile()

    assert "  why: wrong moment, not the wrong book" in text
    # And the instruction for reading it, or it is just another field.
    assert '"wrong moment" means keep suggesting' in text


def test_an_abandoned_book_without_a_note_gets_no_empty_why(library):
    # Scoped past the legend, which explains the field whether or not any book uses it.
    body = build_profile().split("== ABANDONED")[1]

    assert "why:" not in body


def test_nothing_useless_is_spent_on_tokens(library, book):
    """Ids, covers and publishers cost context and tell a recommender nothing."""
    book.publisher = "Audible Studios"
    book.isbn = "9780593135204"
    book.description = "A lone astronaut must save the earth from disaster."
    book.save()

    text = build_profile()

    assert "Audible Studios" not in text
    assert "9780593135204" not in text
    assert book.abs_item_id not in text
    assert "lone astronaut" not in text


def test_an_empty_section_is_not_printed(db, book):
    """A heading with nothing under it is a line of context saying nothing."""
    text = build_profile()

    assert "== REVIEWED" not in text
    assert "== ABANDONED" not in text
    assert "== UNSTARTED" in text  # the one section this library does have


def test_it_stays_small_enough_to_paste(db):
    """A real library is ~450 books. The whole point is that it fits in a prompt."""
    Book.objects.bulk_create(
        Book(abs_item_id=f"b{i}", title=f"Book Number {i}", authors="Some Author")
        for i in range(450)
    )

    text = build_profile()

    assert len(text) < 40_000  # ~10k tokens, comfortably inside any modern window
    # The compact export is legend plus a one-line count, so this bound is really a
    # bound on the legend. It is allowed to grow -- it is what makes every other line
    # mean anything, and it is paid once rather than per book -- but not without
    # somebody noticing.
    assert len(build_profile(include_unstarted=False)) < 4_000


def test_profile_stats_matches_what_the_export_shows(library):
    stats = profile_stats()

    assert stats["reviewed"] == 1
    assert stats["finished"] == 1
    assert stats["unstarted"] == 21


# -- the admin surface --------------------------------------------------------


@pytest.fixture
def staff_client(client, db):
    user = get_user_model().objects.create_superuser("ex", "ex@test", "pw-for-tests-only")
    client.force_login(user)
    return client


def test_the_changelist_offers_both_exports(staff_client, library, settings):
    page = staff_client.get(f"/{settings.ADMIN_PATH}/catalog/book/")

    body = page.content.decode()
    assert reverse("admin:catalog_book_export_profile") in body
    assert "without the to-read pile" in body


def test_the_export_is_plain_utf8_text(staff_client, library):
    response = staff_client.get(reverse("admin:catalog_book_export_profile"))

    assert response.status_code == 200
    assert response["Content-Type"] == "text/plain; charset=utf-8"
    # admin_view() adds its own never-cache directives; ours has to survive them.
    assert "no-store" in response["Cache-Control"]
    assert "LISTENING PROFILE" in response.content.decode("utf-8")


def test_non_ascii_titles_survive_the_round_trip(staff_client, library):
    Book.objects.filter(abs_item_id="todo").update(
        title="Ikigai", authors="Héctor García"
    )

    body = staff_client.get(
        reverse("admin:catalog_book_export_profile")
    ).content.decode("utf-8")

    assert "Héctor García" in body


def test_the_compact_flag_reaches_the_builder(staff_client, library):
    full = staff_client.get(reverse("admin:catalog_book_export_profile"))
    compact = staff_client.get(
        reverse("admin:catalog_book_export_profile") + "?compact=1"
    )

    assert len(compact.content) < len(full.content)


def test_an_anonymous_visitor_cannot_read_the_library(client, library, settings):
    """It is one person's entire reading history, which is not a public document."""
    response = client.get(reverse("admin:catalog_book_export_profile"))

    assert response.status_code == 302
    assert f"/{settings.ADMIN_PATH}/login/" in response["Location"]


def test_a_non_staff_account_cannot_read_it_either(client, library):
    reader = get_user_model().objects.create_user("reader", "r@test", "pw-for-tests-only")
    client.force_login(reader)

    response = client.get(reverse("admin:catalog_book_export_profile"))

    assert response.status_code == 302  # bounced to the admin login, not served


def test_the_management_command_prints_the_same_thing(library, capsys):
    from django.core.management import call_command

    call_command("export_profile")

    assert "LISTENING PROFILE" in capsys.readouterr().out
