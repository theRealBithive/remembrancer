"""The nightly Audiobookshelf pull.

Three behaviours here are load-bearing and are covered by tests:
  1. Re-match order -- keeps a published review attached across an ABS re-add.
  2. Orphan, never delete -- a vanished upstream item must not take a review with it.
  3. Loud auth failure -- see AbsAuthError; a swallowed 401 silently kills the queue.
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass, field

from django.core.files.base import ContentFile
from django.utils.dateparse import parse_datetime
from PIL import Image, UnidentifiedImageError

from catalog.abs import AbsClient, AbsError
from catalog.models import Book, normalize_match_key
from remembrancer.revalidate import revalidate

log = logging.getLogger(__name__)

THUMB_MAX = (300, 300)

# Fields the mirror overwrites on every run. Metadata is a cache (Decision 15):
# fixing a typo in ABS fixes it on the site.
MIRRORED_FIELDS = (
    "abs_library_id", "asin", "isbn", "match_key", "title", "subtitle", "authors",
    "narrators", "series", "series_sequence", "publisher", "published_year",
    "description", "duration_seconds",
)


@dataclass
class SyncReport:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    orphaned: int = 0
    covers_fetched: int = 0
    cover_errors: list[str] = field(default_factory=list)
    revalidated: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"created={self.created} updated={self.updated} unchanged={self.unchanged} "
            f"orphaned={self.orphaned} covers={self.covers_fetched} "
            f"cover_errors={len(self.cover_errors)} revalidated={len(self.revalidated)}"
        )


def _join(values) -> str:
    """ABS returns author/narrator as either a string or a list of objects."""
    if not values:
        return ""
    if isinstance(values, str):
        return values.strip()
    names = []
    for v in values:
        name = v.get("name") if isinstance(v, dict) else v
        if name:
            names.append(str(name).strip())
    return ", ".join(names)


def _year(value) -> int | None:
    try:
        year = int(str(value)[:4])
    except (TypeError, ValueError):
        return None
    return year if 800 <= year <= 2200 else None


def extract_fields(item: dict) -> dict:
    """Flatten an ABS library item into Book field values."""
    media = item.get("media") or {}
    meta = media.get("metadata") or {}
    series = meta.get("series") or []
    first_series = series[0] if isinstance(series, list) and series else {}
    if isinstance(first_series, str):
        first_series = {"name": first_series}

    title = (meta.get("title") or "").strip()
    authors = _join(meta.get("authors") or meta.get("authorName"))
    duration = media.get("duration") or meta.get("duration")

    return {
        "abs_library_id": item.get("libraryId") or "",
        "asin": (meta.get("asin") or "").strip(),
        "isbn": (meta.get("isbn") or "").strip(),
        "match_key": normalize_match_key(title, authors.split(",")[0] if authors else ""),
        "title": title or "(untitled)",
        "subtitle": (meta.get("subtitle") or "").strip(),
        "authors": authors,
        "narrators": _join(meta.get("narrators") or meta.get("narratorName")),
        "series": (first_series.get("name") or "").strip(),
        "series_sequence": str(first_series.get("sequence") or "").strip(),
        "publisher": (meta.get("publisher") or "").strip(),
        "published_year": _year(meta.get("publishedYear") or meta.get("publishedDate")),
        "description": (meta.get("description") or "").strip(),
        "duration_seconds": int(duration) if duration else None,
    }


def cover_fingerprint(item: dict) -> str:
    """Cheap change-detector so covers are re-downloaded only when they actually change."""
    media = item.get("media") or {}
    parts = [
        str(media.get("coverPath") or ""),
        str(item.get("updatedAt") or ""),
        str((media.get("metadata") or {}).get("titleIgnorePrefix") or ""),
    ]
    if not any(parts):
        return ""
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def store_cover(book: Book, raw: bytes) -> None:
    """Save the full cover plus a ~300px thumbnail.

    Producing the thumbnail here means the frontend needs no image optimizer, which
    keeps `next/image` on `unoptimized` and removes sharp from the Node image.
    """
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise AbsError(f"cover is not a decodable image: {exc}") from exc

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    # Django's storage suffixes rather than overwrites on a name collision, so
    # without this every cover change would leave the previous file orphaned on
    # disk and the media volume would grow without bound.
    for existing in (book.cover, book.cover_thumb):
        if existing:
            existing.delete(save=False)

    stem = f"{book.abs_item_id}.jpg"
    full = io.BytesIO()
    image.save(full, format="JPEG", quality=88, optimize=True)
    book.cover.save(stem, ContentFile(full.getvalue()), save=False)

    thumb = image.copy()
    thumb.thumbnail(THUMB_MAX, Image.LANCZOS)
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=82, optimize=True)
    book.cover_thumb.save(stem, ContentFile(buf.getvalue()), save=False)


def sync(client: AbsClient | None = None) -> SyncReport:
    client = client or AbsClient()
    report = SyncReport()
    progress = client.media_progress()
    seen_ids: set[int] = set()
    changed_books: list[Book] = []

    for library_id in client.book_library_ids():
        for item in client.library_items(library_id):
            abs_id = item.get("id")
            if not abs_id:
                continue
            fields = extract_fields(item)

            book = Book.match(
                abs_item_id=abs_id,
                asin=fields["asin"],
                isbn=fields["isbn"],
                match_key=fields["match_key"],
                claimed=seen_ids,
            )
            if book is None:
                book = Book(abs_item_id=abs_id)
                created = True
            else:
                created = False
                # Re-adopt the current upstream id; the old UUID is gone.
                book.abs_item_id = abs_id

            dirty = created or book.is_orphaned
            for name in MIRRORED_FIELDS:
                if getattr(book, name) != fields[name]:
                    setattr(book, name, fields[name])
                    dirty = True
            book.is_orphaned = False

            entry = progress.get(abs_id) or {}
            finished = bool(entry.get("isFinished"))
            finished_at = parse_datetime(entry.get("finishedAt") or "") if entry.get(
                "finishedAt"
            ) else None
            if book.is_finished != finished or book.finished_at != finished_at:
                book.is_finished = finished
                book.finished_at = finished_at
                dirty = True

            fingerprint = cover_fingerprint(item)
            needs_cover = bool(fingerprint) and (
                fingerprint != book.cover_source_hash or not book.cover
            )
            if needs_cover:
                try:
                    raw, _ = client.cover_bytes(abs_id)
                    store_cover(book, raw)
                    book.cover_source_hash = fingerprint
                    report.covers_fetched += 1
                    dirty = True
                except AbsError as exc:
                    # A bad cover must not abort the run or lose the metadata.
                    report.cover_errors.append(f"{fields['title']}: {exc}")
                    log.warning("Cover fetch failed for %s: %s", fields["title"], exc)

            if dirty:
                book.save()
                report.created += created
                report.updated += not created
                changed_books.append(book)
            else:
                book.save(update_fields=["synced_at"])
                report.unchanged += 1

            seen_ids.add(book.pk)

    report.orphaned = Book.objects.exclude(pk__in=seen_ids).filter(is_orphaned=False).update(
        is_orphaned=True
    )

    report.revalidated = _revalidate_affected(changed_books)
    return report


def _revalidate_affected(books: list[Book]) -> list[str]:
    """Refresh any published page whose underlying book metadata moved."""
    from reviews.models import Review  # local import: avoids a catalog<->reviews cycle

    slugs = list(
        Review.objects.filter(
            book__in=books, status=Review.Status.PUBLISHED, slug__isnull=False
        ).values_list("slug", flat=True)
    )
    if not slugs:
        return []
    paths = ["/"] + [f"/reviews/{slug}" for slug in slugs]
    revalidate(paths)
    return paths
