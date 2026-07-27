"""The beacon: counts once per visitor, stores nothing identifying, stays cheap."""

import datetime

import pytest
from django.core.cache import cache
from django.utils import timezone

from reviews.counting import DEDUP_TTL, daily_salt, record_view, visitor_key
from reviews.models import Review, ReviewViewDay

pytestmark = pytest.mark.django_db


def beacon(client, slug, **extra):
    return client.post(f"/api/reviews/{slug}/view", content_type="application/json", **extra)


# -- the endpoint -------------------------------------------------------------


def test_a_view_is_counted_and_the_total_comes_back(client, published_review):
    response = beacon(client, published_review.slug)

    assert response.status_code == 200
    assert response.json() == {"count": 1}
    published_review.refresh_from_db()
    assert published_review.view_count == 1


def test_the_same_visitor_is_not_counted_twice(client, published_review):
    beacon(client, published_review.slug)
    second = beacon(client, published_review.slug)

    assert second.json() == {"count": 1}  # still gets a number, just not a new one
    published_review.refresh_from_db()
    assert published_review.view_count == 1


def test_a_different_visitor_is_counted(client, published_review):
    beacon(client, published_review.slug, HTTP_X_REAL_IP="10.0.0.1", HTTP_USER_AGENT="A")
    beacon(client, published_review.slug, HTTP_X_REAL_IP="10.0.0.2", HTTP_USER_AGENT="A")

    published_review.refresh_from_db()
    assert published_review.view_count == 2


def test_dedup_is_per_review_not_per_visitor(client, published_review, book):
    from catalog.models import Book

    other = Book.objects.create(abs_item_id="item-9", title="Ubik", authors="Philip K. Dick")
    second = Review.objects.create(
        book=other, rating_overall=8, summary="s", status=Review.Status.PUBLISHED
    )

    beacon(client, published_review.slug)
    beacon(client, second.slug)

    published_review.refresh_from_db()
    second.refresh_from_db()
    assert (published_review.view_count, second.view_count) == (1, 1)


def test_a_draft_is_indistinguishable_from_a_missing_slug(client, published_review):
    published_review.status = Review.Status.DRAFT
    published_review.save()

    assert beacon(client, published_review.slug).status_code == 404
    assert beacon(client, "no-such-review").status_code == 404


def test_a_bodyless_post_is_accepted(client, published_review):
    """What the browser actually sends: no body, no Content-Type, no preflight."""
    response = client.post(f"/api/reviews/{published_review.slug}/view")

    assert response.status_code == 200
    assert response.json() == {"count": 1}


def test_the_beacon_needs_no_csrf_token(client, published_review):
    """It is called cross-context from a static page and carries no session.

    A world-writable counter is inherent to a no-cookie design; the throttle bounds
    the noise. Asserted so that adding CSRF later is a deliberate act, not a surprise.
    """
    assert beacon(client, published_review.slug).status_code == 200


def beacon_throttle():
    """The live throttle instance the URLconf is wired to.

    Reloading the module would build a second one that no route points at, so the
    rate has to be adjusted in place on the object actually doing the work.
    """
    from reviews.api import api

    for _, router in api._routers:
        for path_view in router.path_operations.values():
            for operation in path_view.operations:
                if operation.view_func.__name__ == "count_view":
                    (throttle,) = operation.throttle_objects
                    return throttle
    raise AssertionError("the beacon route has no throttle attached")


def test_the_beacon_is_throttled(client, published_review):
    throttle = beacon_throttle()
    original = throttle.num_requests
    throttle.num_requests = 2
    try:
        codes = [beacon(client, published_review.slug).status_code for _ in range(4)]
    finally:
        throttle.num_requests = original

    assert codes[:2] == [200, 200]
    assert codes[2:] == [429, 429]


def test_the_throttle_is_keyed_on_the_visitor_not_the_proxy(rf):
    """Keyed on REMOTE_ADDR it would be Caddy's container address, and one noisy
    client would throttle every reader on the site."""
    throttle = beacon_throttle()
    a = rf.post("/", HTTP_X_REAL_IP="10.0.0.1", HTTP_USER_AGENT="A")
    b = rf.post("/", HTTP_X_REAL_IP="10.0.0.2", HTTP_USER_AGENT="A")

    assert throttle.get_cache_key(a) != throttle.get_cache_key(b)


# -- what gets stored ---------------------------------------------------------


def test_daily_buckets_accumulate(client, published_review):
    beacon(client, published_review.slug, HTTP_X_REAL_IP="10.0.0.1")
    beacon(client, published_review.slug, HTTP_X_REAL_IP="10.0.0.2")

    day = ReviewViewDay.objects.get(review=published_review)
    assert day.date == timezone.localdate()
    assert day.count == 2


def test_a_second_day_opens_a_new_bucket(published_review):
    """Buckets are the trend data; collapsing them would lose the whole point."""
    record_view(published_review, "key-a")
    published_review.refresh_from_db()
    ReviewViewDay.objects.filter(review=published_review).update(
        date=timezone.localdate() - datetime.timedelta(days=1)
    )

    record_view(published_review, "key-b")

    assert ReviewViewDay.objects.filter(review=published_review).count() == 2
    published_review.refresh_from_db()
    assert published_review.view_count == 2


def test_buckets_use_local_dates_not_utc(published_review, settings):
    """At 00:30 Berlin time, UTC is still yesterday. The bucket must say today."""
    assert timezone.localdate() == timezone.localtime().date()

    record_view(published_review, "key")

    assert ReviewViewDay.objects.get(review=published_review).date == timezone.localdate()


# -- privacy ------------------------------------------------------------------


def test_the_salt_is_random_and_not_derived_from_the_date(settings):
    """/legal promises the hash is unlinkable after rotation. A predictable salt --
    the date, the SECRET_KEY -- would make that claim false."""
    first = daily_salt()
    cache.clear()
    second = daily_salt()

    assert first != second
    assert len(first) == 64
    assert timezone.localdate().isoformat() not in first
    assert settings.SECRET_KEY not in first


def test_the_salt_is_stable_within_a_day():
    assert daily_salt() == daily_salt()


def test_the_visitor_hash_is_not_reversible_to_an_address(rf):
    request = rf.post("/", HTTP_X_REAL_IP="203.0.113.7", HTTP_USER_AGENT="Mozilla/5.0")

    key = visitor_key(request)

    assert "203.0.113.7" not in key
    assert "Mozilla" not in key
    assert len(key) == 32


def test_rotating_the_salt_makes_yesterdays_hash_uncomputable(rf):
    request = rf.post("/", HTTP_X_REAL_IP="203.0.113.7", HTTP_USER_AGENT="Mozilla/5.0")
    before = visitor_key(request)

    cache.clear()  # what rotation looks like from the outside

    assert visitor_key(request) != before


def test_nothing_identifying_is_persisted(client, published_review):
    beacon(client, published_review.slug, HTTP_X_REAL_IP="203.0.113.7", HTTP_USER_AGENT="UA/1")

    stored = ReviewViewDay.objects.values().first()

    assert set(stored) == {"id", "review_id", "date", "count"}


def test_the_dedup_key_expires(client, published_review):
    beacon(client, published_review.slug, HTTP_X_REAL_IP="203.0.113.7")

    keys = [k for k in cache._cache if "view:" in str(k)]  # locmem internals

    assert keys, "the dedup entry should exist"
    assert DEDUP_TTL == 6 * 60 * 60


# -- cost ---------------------------------------------------------------------


def test_counting_a_view_does_not_revalidate_the_page(published_review, monkeypatch):
    """Otherwise every read triggers a write to Next and the cache never survives."""
    from django.db import transaction

    calls = []
    monkeypatch.setattr("reviews.signals.revalidate", lambda paths: calls.append(paths))
    monkeypatch.setattr(transaction, "on_commit", lambda fn, **kw: fn())

    record_view(published_review, "key")

    assert calls == []


def test_the_review_payload_carries_no_stale_count(client, published_review):
    """It would be baked into an ISR page for an hour; the beacon returns the live one."""
    body = client.get(f"/api/reviews/{published_review.slug}").json()

    assert "view_count" not in body
