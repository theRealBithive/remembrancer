"""Syndication: composition budget, the at-most-once guard, and the admin action."""

import pytest
import responses
from django.utils import timezone

from reviews import tasks
from reviews.mastodon import (
    LINK_WEIGHT,
    MastodonAuthError,
    MastodonError,
    compose_status,
    configured,
    post_status,
)
from reviews.models import Review

URL = "https://mastodon.test/api/v1/statuses"


@pytest.fixture
def mastodon(settings):
    settings.MASTODON_BASE_URL = "https://mastodon.test"
    settings.MASTODON_TOKEN = "token-abc"
    settings.MASTODON_VISIBILITY = "public"
    settings.MASTODON_HASHTAGS = ["bookstodon"]
    settings.MASTODON_MAX_CHARS = 500
    return settings


def weighted_len(text: str, url: str) -> int:
    """Mastodon's own arithmetic: any link counts as LINK_WEIGHT, not its length."""
    return len(text) - len(url) + LINK_WEIGHT


# --- composition -------------------------------------------------------------


def test_status_carries_book_rating_link_and_tags(mastodon, published_review):
    text = compose_status(published_review, "https://remembrancer.test/reviews/phm")

    assert "Project Hail Mary" in text
    assert "Andy Weir" in text
    assert "4.5/5" in text  # rating_overall 9 rendered on the 5-star scale
    assert text.endswith("https://remembrancer.test/reviews/phm\n\n#bookstodon")


def test_long_summary_is_trimmed_to_the_instance_limit(mastodon, published_review):
    published_review.summary = "Ray Porter carries it. " * 60  # ~1380 chars
    url = "https://remembrancer.test/reviews/project-hail-mary"

    text = compose_status(published_review, url)

    assert weighted_len(text, url) <= 500
    assert text.endswith(f"{url}\n\n#bookstodon")
    assert "…" in text  # trimmed, and says so
    assert " …" not in text.replace("\n", " ")  # cut on a word boundary


def test_link_is_never_sacrificed_even_at_an_absurd_limit(mastodon, published_review):
    """The link is the whole point of posting; a toot without it is noise."""
    url = "https://remembrancer.test/reviews/project-hail-mary"

    text = compose_status(published_review, url, max_chars=40)

    assert url in text
    assert "#bookstodon" in text


def test_a_real_url_is_only_charged_link_weight(mastodon, published_review):
    """A 280-char URL must not eat the summary -- Mastodon does not count it.

    Only meaningful with a summary long enough to be trimmed: with a short one both
    fit regardless and the test would pass without measuring anything.
    """
    published_review.summary = "Ray Porter carries it. " * 60
    long_url = "https://remembrancer.test/reviews/" + "x" * 250

    short = compose_status(published_review, "https://a.test/x")
    long = compose_status(published_review, long_url)

    assert len(short) > 400  # the summary really was trimmed, not passed through
    assert long.split("\n\n")[:2] == short.split("\n\n")[:2]
    assert weighted_len(long, long_url) <= 500


def test_untitled_extras_are_omitted_not_rendered_empty(mastodon, published_review):
    published_review.book.authors = ""

    text = compose_status(published_review, "https://remembrancer.test/reviews/phm")

    assert text.startswith("Project Hail Mary · 4.5/5")
    assert "—" not in text.split("\n")[0]


# --- transport ---------------------------------------------------------------


def test_unconfigured_is_a_refusal_not_a_silent_noop(settings):
    settings.MASTODON_BASE_URL = ""
    settings.MASTODON_TOKEN = ""

    assert configured() is False
    with pytest.raises(MastodonError):
        post_status("hi", idempotency_key="k")


def test_plaintext_instance_is_refused_before_the_token_is_sent(mastodon):
    mastodon.MASTODON_BASE_URL = "http://mastodon.test"

    with pytest.raises(MastodonError, match="https"):
        post_status("hi", idempotency_key="k")


@responses.activate
def test_post_sends_bearer_and_idempotency_key(mastodon):
    responses.post(URL, json={"id": "110", "url": "https://mastodon.test/@me/110"})

    status = post_status("hello", idempotency_key="remembrancer-review-1")

    assert status["id"] == "110"
    sent = responses.calls[0].request
    assert sent.headers["Authorization"] == "Bearer token-abc"
    assert sent.headers["Idempotency-Key"] == "remembrancer-review-1"


@responses.activate
def test_missing_scope_is_distinguishable_from_a_generic_failure(mastodon):
    responses.post(URL, status=403, json={"error": "insufficient scope"})

    with pytest.raises(MastodonAuthError, match="write:statuses"):
        post_status("hello", idempotency_key="k")


@responses.activate
def test_a_response_without_an_id_is_not_treated_as_success(mastodon):
    """Otherwise the review is marked posted and can never be retried."""
    responses.post(URL, json={"error": "nope"})

    with pytest.raises(MastodonError, match="no status id"):
        post_status("hello", idempotency_key="k")


# --- the task ----------------------------------------------------------------


@responses.activate
def test_task_records_the_status_id(mastodon, published_review):
    responses.post(URL, json={"id": "110", "url": "https://mastodon.test/@me/110"})

    result = tasks.post_review_to_mastodon(published_review.pk)

    published_review.refresh_from_db()
    assert published_review.mastodon_status_id == "110"
    assert published_review.mastodon_posted_at is not None
    assert result == "https://mastodon.test/@me/110"


@responses.activate
def test_a_retry_does_not_post_twice(mastodon, published_review):
    """django-q2 retries on failure; the guard is what stops a double federation."""
    responses.post(URL, json={"id": "110"})
    tasks.post_review_to_mastodon(published_review.pk)

    tasks.post_review_to_mastodon(published_review.pk)

    assert len(responses.calls) == 1


@responses.activate
def test_a_draft_is_refused(mastodon, published_review):
    published_review.status = Review.Status.DRAFT
    published_review.save()

    with pytest.raises(ValueError, match="not published"):
        tasks.post_review_to_mastodon(published_review.pk)

    assert not responses.calls  # nothing left the box


# --- the admin action --------------------------------------------------------


@pytest.fixture
def admin_action(db):
    from django.contrib.admin.sites import AdminSite

    from reviews.admin import ReviewAdmin

    return ReviewAdmin(Review, AdminSite())


def queue_and_capture(admin_action, rf, admin_user, monkeypatch, queryset):
    queued, messages = [], []
    monkeypatch.setattr(
        "reviews.admin.async_task", lambda *a, **kw: queued.append(a) or "task-id"
    )
    monkeypatch.setattr(
        admin_action,
        "message_user",
        lambda req, msg, level=None, **kw: messages.append((level, msg)),
    )
    request = rf.get("/")
    request.user = admin_user
    admin_action.post_to_mastodon(request, queryset)
    return queued, messages


def test_changelist_offers_the_action_and_renders_the_column(
    client, settings, published_review
):
    """A unit-tested action that blows up on render is still a broken action."""
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_superuser("ed3", "e3@test", "pw-for-tests-only")
    client.force_login(user)
    published_review.mastodon_status_id = "110"
    published_review.mastodon_posted_at = timezone.now()
    published_review.save()

    page = client.get(f"/{settings.ADMIN_PATH}/reviews/review/")

    assert page.status_code == 200
    body = page.content.decode()
    assert "post_to_mastodon" in body
    assert ">posted<" in body


def test_action_refuses_when_unconfigured(
    settings, admin_action, rf, admin_user, monkeypatch, published_review
):
    settings.MASTODON_BASE_URL = ""
    settings.MASTODON_TOKEN = ""

    queued, messages = queue_and_capture(
        admin_action, rf, admin_user, monkeypatch, Review.objects.all()
    )

    assert queued == []
    assert "MASTODON_BASE_URL" in messages[0][1]


def test_action_queues_published_and_reports_what_it_skipped(
    mastodon, admin_action, rf, admin_user, monkeypatch, published_review, book
):
    from catalog.models import Book

    other = Book.objects.create(abs_item_id="item-2", title="Dune", authors="Herbert")
    draft = Review.objects.create(book=other, rating_overall=8, summary="s")
    published_review.mastodon_status_id = "99"
    published_review.mastodon_posted_at = timezone.now()
    published_review.save()
    third = Book.objects.create(abs_item_id="item-3", title="Ubik", authors="Dick")
    fresh = Review.objects.create(
        book=third, rating_overall=8, summary="s", status=Review.Status.PUBLISHED
    )

    queued, messages = queue_and_capture(
        admin_action, rf, admin_user, monkeypatch, Review.objects.all()
    )

    assert [args[1] for args in queued] == [fresh.pk]
    text = " ".join(m for _, m in messages)
    assert "Dune (not published)" in text
    assert "Project Hail Mary (already posted)" in text
    assert draft.pk not in [args[1] for args in queued]
