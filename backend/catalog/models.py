"""Mirrored Audiobookshelf state.

Everything here is a cache: the nightly sync overwrites it freely (Decision 15).
Nothing in this module may be the only copy of anything you authored -- that lives
in `reviews`, which is why the two apps are separate.
"""

import re
import unicodedata
from datetime import timedelta

from django.db import models
from django.utils import timezone

# What counts as abandoned. Tuned against a real 456-book library: 90 days of silence
# under 15% is unambiguous, and the 5-minute floor separates a verdict from a mis-tap
# -- a book opened for ninety seconds was never begun and says nothing worth writing.
ABANDONED_IDLE_DAYS = 90
ABANDONED_MAX_PROGRESS = 0.15
ABANDONED_MIN_SECONDS = 300


def abandoned_cutoff():
    return timezone.now() - timedelta(days=ABANDONED_IDLE_DAYS)


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

    # --- listening record --------------------------------------------------
    # How long a book took, relative to its length, is the strongest available
    # signal of how much it was enjoyed: a 14h book finished in four days was
    # devoured, the same book spread over a year was endured.
    is_finished = models.BooleanField(default=False, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_played_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Last progress update. Silence since is what marks a book abandoned.",
    )
    progress = models.FloatField(default=0.0, help_text="0..1, from ABS.")
    seconds_listened = models.PositiveIntegerField(null=True, blank=True)

    is_orphaned = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Absent from the last sync. Never deleted -- a review may depend on it.",
    )

    # The one authored value in an otherwise disposable mirror, which is why it is
    # absent from sync.MIRRORED_FIELDS. It hides the *title*: a hidden book still
    # counts toward the year total, because a number reveals nothing and a count that
    # silently disagreed with the library would be worse than no count.
    hide_from_public = models.BooleanField(
        default=False,
        help_text="Keep this book out of “now listening” on the public page. "
        "The sync never touches this box.",
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

    # -- listening pace -----------------------------------------------------

    @property
    def days_to_finish(self) -> float | None:
        """Calendar days between first play and finishing."""
        if not (self.started_at and self.finished_at):
            return None
        elapsed = (self.finished_at - self.started_at).total_seconds()
        return elapsed / 86400 if elapsed > 0 else None

    @property
    def listening_pace(self) -> float | None:
        """Hours of audio consumed per calendar day.

        Normalises length away, which is the whole point: four days on a 14h book is
        a different act from four days on a 3h one. Playback speed means this can
        legitimately exceed 24, so it is not capped -- but a run under an hour is
        treated as same-day to keep the divisor from exploding.
        """
        days = self.days_to_finish
        if days is None or not self.duration_seconds:
            return None
        return (self.duration_seconds / 3600) / max(days, 1 / 24)

    @property
    def is_abandoned(self) -> bool:
        """Started, barely got anywhere, and untouched since. See ABANDONED_*."""
        if self.is_finished or self.is_orphaned or not self.last_played_at:
            return False
        if (self.seconds_listened or 0) < ABANDONED_MIN_SECONDS:
            return False
        if self.progress >= ABANDONED_MAX_PROGRESS:
            return False
        return self.last_played_at <= abandoned_cutoff()

    @staticmethod
    def abandoned_q() -> models.Q:
        """The SQL twin of `is_abandoned`, for filtering a changelist.

        Kept beside it deliberately: two definitions of "abandoned" that drift apart
        would show one set of books in the queue and a different flag on each row.
        """
        return models.Q(
            is_finished=False,
            is_orphaned=False,
            last_played_at__isnull=False,
            last_played_at__lte=abandoned_cutoff(),
            seconds_listened__gte=ABANDONED_MIN_SECONDS,
            progress__lt=ABANDONED_MAX_PROGRESS,
        )

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
