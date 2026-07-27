"""Audiobookshelf HTTP client.

Endpoint shapes verified against api.audiobookshelf.org:
  POST /login                      -> {"user": {"token": ...}}
  GET  /api/libraries              -> {"libraries": [...]}
  GET  /api/libraries/{id}/items   -> {"results": [...], "total": n, "page": p, ...}
                                      page is ZERO-indexed
  GET  /api/me                     -> {..., "mediaProgress": [...]}
  GET  /api/items/{id}/cover       -> image bytes, Bearer auth
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

import requests
from django.conf import settings

log = logging.getLogger(__name__)

PAGE_SIZE = 100


class AbsError(RuntimeError):
    """Any failure talking to ABS."""


class AbsAuthError(AbsError):
    """401/403 from ABS.

    Raised, never swallowed. A silently expired token would stop the finished-book
    queue -- the single mechanism the whole review nudge depends on (Decision 3).
    """


class AbsClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or settings.ABS_BASE_URL).rstrip("/")
        self.token = token or settings.ABS_TOKEN
        if not self.base_url:
            raise AbsError("ABS_BASE_URL is not configured.")
        if not self.token:
            raise AbsAuthError("ABS_TOKEN is not configured.")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {self.token}"

    # -- internals ----------------------------------------------------------

    def _get(self, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(url, timeout=settings.ABS_TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise AbsError(f"GET {path} failed: {exc}") from exc
        if resp.status_code in (401, 403):
            raise AbsAuthError(
                f"ABS rejected the token on {path} ({resp.status_code}). "
                "Regenerate ABS_TOKEN -- sync is stopped until you do."
            )
        if not resp.ok:
            raise AbsError(f"GET {path} returned {resp.status_code}")
        return resp

    # -- endpoints ----------------------------------------------------------

    def libraries(self) -> list[dict]:
        return self._get("/api/libraries").json().get("libraries", [])

    def book_library_ids(self) -> list[str]:
        """Configured library IDs, or every library whose mediaType is 'book'."""
        if settings.ABS_LIBRARY_IDS:
            return list(settings.ABS_LIBRARY_IDS)
        return [
            lib["id"] for lib in self.libraries() if lib.get("mediaType", "book") == "book"
        ]

    def library_items(self, library_id: str):
        """Yield every item in a library, walking the zero-indexed page envelope."""
        page = 0
        seen = 0
        while True:
            payload = self._get(
                f"/api/libraries/{library_id}/items",
                params={"limit": PAGE_SIZE, "page": page},
            ).json()
            results = payload.get("results", [])
            if not results:
                return
            yield from results
            seen += len(results)
            total = payload.get("total")
            if total is not None and seen >= total:
                return
            page += 1

    def media_progress(self) -> dict[str, dict]:
        """`/api/me` -> {libraryItemId: progress}. Drives the finished-book queue."""
        payload = self._get("/api/me").json()
        return {
            entry["libraryItemId"]: entry
            for entry in payload.get("mediaProgress", [])
            if entry.get("libraryItemId")
        }

    def cover_bytes(self, item_id: str) -> tuple[bytes, str]:
        """Download a cover, bounded and content-type checked.

        This is the one place the backend fetches a remote resource on a schedule, so
        it is treated as SSRF-adjacent: the URL is always composed from the configured
        ABS host, and any redirect off that host is refused.
        """
        resp = self._get(f"/api/items/{item_id}/cover", stream=True, allow_redirects=False)

        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            target = resp.headers.get("Location", "")
            if urlsplit(target).netloc not in ("", urlsplit(self.base_url).netloc):
                raise AbsError(f"Cover for {item_id} redirects off-host to {target!r}; refused.")
            resp = self._get(f"/api/items/{item_id}/cover", stream=True)

        content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
        if not content_type.startswith("image/"):
            raise AbsError(f"Cover for {item_id} is {content_type!r}, not an image.")

        limit = settings.ABS_MAX_COVER_BYTES
        chunks, size = [], 0
        for chunk in resp.iter_content(64 * 1024):
            size += len(chunk)
            if size > limit:
                raise AbsError(f"Cover for {item_id} exceeds {limit} bytes; refused.")
            chunks.append(chunk)
        return b"".join(chunks), content_type
