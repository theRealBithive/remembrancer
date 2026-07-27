"""Write-path and revalidation guards."""

import json
import secrets
from pathlib import Path

import pytest
import responses
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from remembrancer.client_ip import client_ip
from remembrancer.revalidate import revalidate, sign
from reviews.models import Review

pytestmark = pytest.mark.django_db


# -- login throttling must key on the client, not on the proxy ---------------

def test_lockouts_key_on_the_real_client_not_the_proxy(rf, settings):
    """Behind Caddy, REMOTE_ADDR is the proxy on every request.

    If axes resolves that, all attackers share one bucket and five wrong passwords
    from anyone on the internet lock the operator out of the only write path.
    """
    from axes.helpers import get_client_ip_address

    request = rf.post("/steward/login/", REMOTE_ADDR="192.168.48.6",
                      HTTP_X_REAL_IP="203.0.113.9")

    assert settings.AXES_CLIENT_IP_CALLABLE == "remembrancer.client_ip.client_ip"
    assert get_client_ip_address(request) == "203.0.113.9"


def test_forwarded_for_cannot_forge_a_lockout_identity():
    """Caddy appends to XFF but overwrites X-Real-IP, so only the latter is trusted."""
    request = RequestFactory().post(
        "/steward/login/",
        REMOTE_ADDR="192.168.48.6",
        HTTP_X_REAL_IP="203.0.113.9",
        HTTP_X_FORWARDED_FOR="8.8.8.8, 203.0.113.9",
    )

    assert client_ip(request) == "203.0.113.9", "attacker-supplied XFF must be ignored"


def test_client_ip_falls_back_when_the_proxy_is_bypassed():
    assert client_ip(RequestFactory().get("/", REMOTE_ADDR="10.0.0.5")) == "10.0.0.5"


# -- the admin is the only write path ---------------------------------------

def test_admin_redirects_anonymous_users_to_login(client, settings):
    resp = client.get(f"/{settings.ADMIN_PATH}/reviews/review/")

    assert resp.status_code == 302
    assert "login" in resp["Location"]


def test_api_exposes_no_write_verbs(client, published_review):
    for method in (client.post, client.put, client.patch, client.delete):
        assert method(f"/api/reviews/{published_review.slug}").status_code in (404, 405)


def test_staff_can_author_a_review(client, book, settings):
    user = get_user_model().objects.create_superuser("me", "me@example.test", "pw-for-tests-only")
    client.force_login(user)

    resp = client.post(
        f"/{settings.ADMIN_PATH}/reviews/review/add/",
        {
            "book": book.pk,
            "status": Review.Status.PUBLISHED,
            "rating_overall": 9,
            "rating_narration": 10,
            "summary": "Ray Porter carries it.",
            "body_markdown": "Good.",
        },
    )

    assert resp.status_code == 302, resp.context["adminform"].form.errors if resp.context else ""
    assert Review.objects.get().slug == "project-hail-mary-andy-weir"


# -- revalidation hook ------------------------------------------------------

@responses.activate
def test_revalidate_signs_the_body(settings):
    settings.REVALIDATE_SECRET = "s3cret"
    settings.NEXT_INTERNAL_URL = "http://next:3000"
    responses.post("http://next:3000/api/revalidate", json={"revalidated": True})

    assert revalidate(["/reviews/a"]) is True

    call = responses.calls[0].request
    assert call.headers["X-Signature"] == sign(call.body)
    assert json.loads(call.body)["paths"] == ["/reviews/a"]


def test_revalidate_is_a_noop_without_a_secret(settings):
    settings.REVALIDATE_SECRET = ""

    assert revalidate(["/reviews/a"]) is False


@responses.activate
def test_publishing_survives_an_unreachable_frontend(settings, book):
    """A publish must never fail because Next is down -- ISR's time-based
    revalidate is the fallback, so the worst case is a stale page."""
    settings.REVALIDATE_SECRET = "s3cret"
    responses.post("http://next:3000/api/revalidate", body=ConnectionError("down"))

    review = Review.objects.create(book=book, rating_overall=8, summary="s",
                                   status=Review.Status.PUBLISHED)

    assert review.slug is not None


# -- deploy guards ----------------------------------------------------------

def test_deploy_check_rejects_placeholder_secrets(settings):
    from remembrancer.checks import check_production_secrets

    settings.SECRET_KEY = settings.INSECURE_PLACEHOLDER
    settings.REVALIDATE_SECRET = ""
    settings.SITE_URL = "http://localhost:3000"

    ids = {p.id for p in check_production_secrets(None)}

    assert {"remembrancer.E001", "remembrancer.E002", "remembrancer.E003"} <= ids


def test_deploy_check_rejects_the_values_shipped_in_env_example(settings):
    """`cp .env.example .env` is the documented first run.

    If the gate only knew the settings default, a deploy that skipped two lines would
    boot with secrets published in this repository.
    """
    from remembrancer.checks import check_production_secrets

    example = Path(settings.BASE_DIR).parent / ".env.example"
    values = dict(
        line.split("=", 1)
        for line in example.read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    settings.SECRET_KEY = values["DJANGO_SECRET_KEY"]
    settings.REVALIDATE_SECRET = values["REVALIDATE_SECRET"]

    ids = {p.id for p in check_production_secrets(None)}

    assert "remembrancer.E001" in ids, "the example SECRET_KEY must not boot"
    assert "remembrancer.E002" in ids, "the example REVALIDATE_SECRET must not boot"


def test_deploy_check_accepts_real_secrets(settings):
    from remembrancer.checks import check_production_secrets

    settings.SECRET_KEY = secrets.token_urlsafe(64)
    settings.REVALIDATE_SECRET = secrets.token_urlsafe(64)
    settings.SITE_URL = "https://remembrancer.example"

    ids = {p.id for p in check_production_secrets(None)}

    assert not {"remembrancer.E001", "remembrancer.E002", "remembrancer.E003"} & ids


# -- authoring flow ----------------------------------------------------------

def test_book_changelist_links_straight_into_a_prefilled_review_form(client, book, settings):
    """Starting from the book beats hunting for it in a select of the whole library."""
    user = get_user_model().objects.create_superuser("ed", "ed@example.test", "pw-for-tests-only")
    client.force_login(user)

    listing = client.get(f"/{settings.ADMIN_PATH}/catalog/book/")
    add_url = f"/{settings.ADMIN_PATH}/reviews/review/add/?book={book.pk}"

    assert add_url in listing.content.decode()

    form = client.get(add_url)
    assert form.status_code == 200
    assert form.context["adminform"].form.initial["book"] == str(book.pk)


def test_autocomplete_hides_books_that_already_have_a_review(client, book, settings):
    user = get_user_model().objects.create_superuser("ed2", "e2@example.test", "pw-for-tests-only")
    client.force_login(user)
    url = (f"/{settings.ADMIN_PATH}/autocomplete/?app_label=reviews&model_name=review"
           f"&field_name=book&term={book.title[:6]}")

    before = json.loads(client.get(url).content)["results"]
    Review.objects.create(book=book, rating_overall=8, summary="Done.")
    after = json.loads(client.get(url).content)["results"]

    assert [r["id"] for r in before] == [str(book.pk)]
    assert after == [], "a book with a review must not be offered again"
