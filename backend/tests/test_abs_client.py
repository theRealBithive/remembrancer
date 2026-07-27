"""HTTP-level behaviour of the Audiobookshelf client."""

import pytest
import responses

from catalog.abs import AbsAuthError, AbsClient, AbsError
from tests.conftest import abs_item, jpeg_bytes

BASE = "https://abs.test"


@pytest.fixture
def client(settings):
    settings.ABS_BASE_URL = BASE
    settings.ABS_TOKEN = "t0ken"
    settings.ABS_LIBRARY_IDS = []
    return AbsClient()


@responses.activate
def test_pagination_walks_the_zero_indexed_envelope(client):
    page_0 = [abs_item(item_id=f"i{n}") for n in range(100)]
    page_1 = [abs_item(item_id="i100")]
    responses.get(f"{BASE}/api/libraries/lib-1/items",
                  json={"results": page_0, "total": 101, "page": 0})
    responses.get(f"{BASE}/api/libraries/lib-1/items",
                  json={"results": page_1, "total": 101, "page": 1})

    assert len(list(client.library_items("lib-1"))) == 101


@responses.activate
def test_pagination_stops_at_total_without_a_wasted_request(client):
    responses.get(f"{BASE}/api/libraries/lib-1/items",
                  json={"results": [abs_item()], "total": 1, "page": 0})

    assert len(list(client.library_items("lib-1"))) == 1
    assert len(responses.calls) == 1


@responses.activate
def test_401_raises_auth_error_rather_than_returning_empty(client):
    responses.get(f"{BASE}/api/me", status=401, json={"error": "unauthorized"})

    with pytest.raises(AbsAuthError, match="Regenerate ABS_TOKEN"):
        client.media_progress()


@responses.activate
def test_only_book_libraries_are_synced(client):
    responses.get(f"{BASE}/api/libraries", json={"libraries": [
        {"id": "lib-1", "mediaType": "book"},
        {"id": "lib-2", "mediaType": "podcast"},
    ]})

    assert client.book_library_ids() == ["lib-1"]


@responses.activate
def test_cover_rejects_non_image_content_type(client):
    responses.get(f"{BASE}/api/items/x/cover", body="<html>login</html>",
                  content_type="text/html")

    with pytest.raises(AbsError, match="not an image"):
        client.cover_bytes("x")


@responses.activate
def test_cover_rejects_oversized_payload(client, settings):
    settings.ABS_MAX_COVER_BYTES = 1024
    responses.get(f"{BASE}/api/items/x/cover", body=jpeg_bytes((2000, 2000)),
                  content_type="image/jpeg")

    with pytest.raises(AbsError, match="exceeds"):
        client.cover_bytes("x")


@responses.activate
def test_cover_refuses_an_off_host_redirect(client):
    """SSRF guard: the sync fetches remote URLs on a timer, so a redirect off the
    configured ABS host is refused rather than followed."""
    responses.get(f"{BASE}/api/items/x/cover", status=302,
                  headers={"Location": "http://169.254.169.254/latest/meta-data/"})

    with pytest.raises(AbsError, match="redirects off-host"):
        client.cover_bytes("x")


def test_missing_token_fails_at_construction(settings):
    settings.ABS_BASE_URL = BASE
    settings.ABS_TOKEN = ""

    with pytest.raises(AbsAuthError):
        AbsClient()
