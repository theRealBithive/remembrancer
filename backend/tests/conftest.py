import io

import pytest
from PIL import Image

from catalog.models import Book
from reviews.models import Review


@pytest.fixture(autouse=True)
def media_root(tmp_path, settings):
    # Named `media_root`, not `test_environment` -- pytest-django ships a fixture by
    # that name and defining our own would silently replace it.
    """Never write cover files into the working tree during tests.

    SECURE_SSL_REDIRECT is on in every non-DEBUG environment, which would turn every
    test-client request into a 301 before the view ever runs. The redirect itself is
    verified against the real proxy in the deployment checks, not here.
    """
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.SITE_URL = "https://remembrancer.test"
    settings.SECURE_SSL_REDIRECT = False
    return settings.MEDIA_ROOT


def jpeg_bytes(size=(600, 900), colour=(30, 40, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="JPEG")
    return buf.getvalue()


def abs_item(
    item_id="item-1",
    title="Project Hail Mary",
    author="Andy Weir",
    asin="B08GB58KD5",
    isbn="",
    updated_at=1700000000,
) -> dict:
    """Shape mirrors a real /api/libraries/{id}/items result entry."""
    return {
        "id": item_id,
        "libraryId": "lib-1",
        "updatedAt": updated_at,
        "media": {
            "duration": 60 * 60 * 16,
            "coverPath": f"/audiobooks/{item_id}/cover.jpg",
            "metadata": {
                "title": title,
                "subtitle": "",
                "authors": [{"name": author}],
                "narrators": [{"name": "Ray Porter"}],
                "series": [{"name": "Standalone", "sequence": "1"}],
                "publisher": "Audible Studios",
                "publishedYear": "2021",
                "description": "A lone astronaut.",
                "asin": asin,
                "isbn": isbn,
            },
        },
    }


class FakeAbsClient:
    """Stands in for AbsClient at the seam sync() actually depends on.

    HTTP-level behaviour (pagination, 401, cover guards) is covered separately in
    test_abs_client.py against `responses`; this keeps the sync-logic tests readable.
    """

    def __init__(self, items=None, progress=None, cover=None):
        self.items = items if items is not None else []
        self.progress = progress or {}
        self.cover = cover if cover is not None else jpeg_bytes()
        self.cover_calls = 0

    def book_library_ids(self):
        return ["lib-1"]

    def library_items(self, library_id):
        yield from self.items

    def media_progress(self):
        return self.progress

    def cover_bytes(self, item_id):
        self.cover_calls += 1
        return self.cover, "image/jpeg"


@pytest.fixture
def book(db):
    return Book.objects.create(
        abs_item_id="item-1", title="Project Hail Mary", authors="Andy Weir",
    )


@pytest.fixture
def published_review(db, book):
    return Review.objects.create(
        book=book,
        rating_overall=9,
        rating_narration=10,
        summary="Ray Porter carries an already excellent book.",
        body_markdown="A *lone* astronaut.",
        status=Review.Status.PUBLISHED,
    )
