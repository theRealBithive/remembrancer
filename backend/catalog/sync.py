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
from datetime import UTC, datetime

from django.core.files.base import ContentFile
from django.utils import timezone
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


def _timestamp(value) -> datetime | None:
    """ABS timestamps are epoch **milliseconds**, not ISO strings.

    Observed against a live instance: `finishedAt` comes back as an integer, so the
    obvious `parse_datetime(value or "")` raises TypeError rather than returning None
    -- a truthy non-string sails past the guard. Both shapes are accepted here because
    the ABS API is not consistent about it across versions and endpoints.
    """
    if value in (None, ""):
        return None

    if isinstance(value, str) and not value.lstrip("-").isdigit():
        parsed = parse_datetime(value)
        if parsed is None:
            return None
        return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed, UTC)

    try:
        epoch = float(value)
    except (TypeError, ValueError):
        return None
    if epoch <= 0:
        return None
    # Milliseconds since ~1973 exceed this; seconds would not reach it until the year
    # 5138. Anything larger is therefore ms.
    if epoch > 1e11:
        epoch /= 1000
    try:
        return datetime.fromtimestamp(epoch, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _text(value) -> str:
    """Coerce to a stripped string rather than assuming ABS sent one.

    `(value or "").strip()` raises AttributeError the moment a field arrives as a
    number -- an ISBN or a series sequence, both of which ABS has been seen to emit
    unquoted. A first sync is not the place to discover that.
    """
    if value is None or isinstance(value, (list, dict)):
        return ""
    return str(value).strip()


def _duration(value) -> int | None:
    """Seconds, as a whole number. ABS sends a float."""
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _fraction(value) -> float:
    """ABS `progress`, clamped to 0..1. Absent means never started, which is 0."""
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.0


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

    title = _text(meta.get("title"))
    authors = _join(meta.get("authors") or meta.get("authorName"))
    duration = media.get("duration") or meta.get("duration")

    return {
        "abs_library_id": _text(item.get("libraryId")),
        "asin": _text(meta.get("asin")),
        "isbn": _text(meta.get("isbn")),
        "match_key": normalize_match_key(title, authors.split(",")[0] if authors else ""),
        "title": title or "(untitled)",
        "subtitle": _text(meta.get("subtitle")),
        "authors": authors,
        "narrators": _join(meta.get("narrators") or meta.get("narratorName")),
        "series": _text(first_series.get("name")),
        "series_sequence": _text(first_series.get("sequence")),
        "publisher": _text(meta.get("publisher")),
        "published_year": _year(meta.get("publishedYear") or meta.get("publishedDate")),
        "description": _text(meta.get("description")),
        "duration_seconds": _duration(duration),
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


def no_cover(fingerprint: str) -> str:
    """Marker stored in `cover_source_hash` when ABS reports no cover for an item.

    Distinct from the bare fingerprint so the two states stay tellable apart: "cover
    fetched at this version" versus "confirmed absent at this version".
    """
    return f"{fingerprint}:none"


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
            listening = {
                "is_finished": bool(entry.get("isFinished")),
                "started_at": _timestamp(entry.get("startedAt")),
                "finished_at": _timestamp(entry.get("finishedAt")),
                "last_played_at": _timestamp(entry.get("lastUpdate")),
                "progress": _fraction(entry.get("progress")),
                "seconds_listened": _duration(entry.get("currentTime")),
            }
            for name, value in listening.items():
                if getattr(book, name) != value:
                    setattr(book, name, value)
                    dirty = True

            fingerprint = cover_fingerprint(item)
            # `not book.cover` is what recovers a wiped media volume: the hash still
            # matches but the file is gone, so re-download. NO_COVER records that ABS
            # itself has none, which that clause would otherwise retry forever.
            needs_cover = (
                bool(fingerprint)
                and book.cover_source_hash != no_cover(fingerprint)
                and (fingerprint != book.cover_source_hash or not book.cover)
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
                    if exc.status == 404:
                        # Durably absent, unlike a timeout or a 5xx. A library with
                        # coverless items would otherwise log the same warnings on
                        # every scheduled run, which trains you to ignore the output.
                        # An upstream edit changes the fingerprint and so retries.
                        book.cover_source_hash = no_cover(fingerprint)
                        dirty = True
                        dirty = True

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
