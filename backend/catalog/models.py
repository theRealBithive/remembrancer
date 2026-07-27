"""Mirrored Audiobookshelf state.

Everything here is a cache: the nightly sync overwrites it freely (Decision 15).
Nothing in this module may be the only copy of anything you authored -- that lives
in `reviews`, which is why the two apps are separate.
"""

import re
import unicodedata

from django.db import models


def normalize_match_key(title: str, author: str) -> str:
    """Last-resort identity key for re-matching a book across an ABS remove/re-add.

    Casefolded, accent-stripped, punctuation-free, whitespace-collapsed. Deliberately
    lossy: it only has to survive a library rebuild, not distinguish editions.
    """
    raw = f"{title or ''} {author or ''}"
    decomposed = unicodedata.normalize("NFKD", raw)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", stripped.casefold()).strip()


class Book(models.Model):
    """One Audiobookshelf library item, mirrored locally.

    `abs_item_id` is the sync key but is treated as *mutable*: ABS mints a new UUID
    when an item is removed and re-added, so it cannot be the durable identity.
    See `Book.match` for the fallback chain.
    """

    abs_item_id = models.CharField(max_length=64, unique=True, db_index=True)
    abs_library_id = models.CharField(max_length=64, blank=True)

    asin = models.CharField(max_length=32, blank=True, db_index=True)
    isbn = models.CharField(max_length=32, blank=True, db_index=True)
    match_key = models.CharField(
        max_length=512,
        blank=True,
        db_index=True,
        help_text="Normalized title+author; last resort when ABS re-mints an item id.",
    )

    title = models.CharField(max_length=512)
    subtitle = models.CharField(max_length=512, blank=True)
    authors = models.CharField(max_length=512, blank=True)
    narrators = models.CharField(max_length=512, blank=True)
    series = models.CharField(max_length=256, blank=True)
    series_sequence = models.CharField(max_length=32, blank=True)
    publisher = models.CharField(max_length=256, blank=True)
    published_year = models.PositiveSmallIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)

    cover = models.ImageField(upload_to="covers/", blank=True)
    cover_thumb = models.ImageField(upload_to="covers/thumbs/", blank=True)
    cover_source_hash = models.CharField(
        max_length=128,
        blank=True,
        help_text="Fingerprint of the upstream cover; re-download only when it changes.",
    )

    is_finished = models.BooleanField(default=False, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    is_orphaned = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Absent from the last sync. Never deleted -- a review may depend on it.",
    )
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        indexes = [models.Index(fields=["is_finished", "is_orphaned"])]

    def __str__(self) -> str:
        return f"{self.title} — {self.authors}" if self.authors else self.title

    @property
    def primary_author(self) -> str:
        return self.authors.split(",")[0].strip() if self.authors else ""

    @classmethod
    def match(cls, *, abs_item_id: str, asin: str, isbn: str, match_key: str, claimed=()):
        """Find an existing Book in decreasing order of identity strength.

        This chain is the whole reason a published review stays attached to its book
        when the underlying ABS item is removed and re-added with a fresh UUID.

        `claimed` holds the pks already taken by earlier items in the same sync run.
        Without it, two distinct ABS items sharing an ASIN -- the same book present in
        two libraries -- both resolve to one row, and the second silently overwrites
        the first instead of becoming its own book.
        """
        for lookup in (
            {"abs_item_id": abs_item_id},
            {"asin": asin} if asin else None,
            {"isbn": isbn} if isbn else None,
            {"match_key": match_key} if match_key else None,
        ):
            if not lookup:
                continue
            # A weak key can legitimately match more than one row (two editions of the
            # same title). Ambiguity means "not confident" -- fall through rather than
            # silently attach a review to the wrong book.
            found = list(cls.objects.exclude(pk__in=claimed).filter(**lookup)[:2])
            if len(found) == 1:
                return found[0]
        return None
