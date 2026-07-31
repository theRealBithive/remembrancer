"""Authored state.

Unlike `catalog`, nothing here is ever overwritten by a sync. The two invariants
that matter are enforced in `save()` rather than only in the admin, because a
published URL is permanent once it federates:

  * a slug is assigned at first publish and never changes;
  * drafts carry NULL (not "") so many of them coexist under a unique index.
"""

from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from catalog.models import Book
from reviews.markdown import render_markdown, summarise_markdown

# Ratings are stored as half-steps: 1..10 == 0.5..5.0 stars.
RATING_MIN, RATING_MAX = 1, 10

# Roughly what a Mastodon or Slack card shows before it clips. Longer costs nothing
# but is never read.
CARD_DESCRIPTION_CHARS = 200


class Review(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"

    # PROTECT: a book carrying a review must never be deletable out from under it.
    # OneToOne: Decision 19 -- one review per book, forever. Edit in place on a re-listen.
    book = models.OneToOneField(Book, on_delete=models.PROTECT, related_name="review")

    slug = models.SlugField(
        max_length=200,
        unique=True,
        null=True,
        blank=True,
        help_text="Assigned at first publish, then frozen. Federated links must never 404.",
    )

    rating_overall = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(RATING_MIN), MaxValueValidator(RATING_MAX)],
        help_text="Half-steps: 1–10 renders as 0.5–5 stars.",
    )
    rating_narration = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(RATING_MIN), MaxValueValidator(RATING_MAX)],
        help_text="Optional. A great book can have a poor reader.",
    )

    # Orm, from Walter Moers' Zamonien novels: the force that runs through a writer
    # when the work is more than well made. A separate axis from the rating on purpose
    # -- craft and effect diverge, and the site had no way to say the second thing.
    #
    # Deliberately not nullable, and `False` is not a hedge. Setting it is the whole
    # act; leaving it alone says the book was good and no more than good. "Not yet
    # decided" is already expressed structurally, by a book having no review at all.
    had_orm = models.BooleanField(
        "Orm",
        default=False,
        help_text="Rare. Not a higher rating -- a different axis. Tick it only for a "
        "book that did something to you beyond being good.",
    )

    summary = models.CharField(
        max_length=300,
        blank=True,
        help_text="Optional. Becomes og:description and the Mastodon post, so it should "
        "read as a sentence rather than a truncated first paragraph. Leave it empty and "
        "the card falls back to the body, then to the rating on its own.",
    )
    body_markdown = models.TextField(blank=True, help_text="Markdown. Optional.")

    # Written by a model, not by me, and shown collapsed on the page for exactly that
    # reason. Deliberately absent from `card_description`, the feed, the toot and the
    # LLM export: it is generated *from* the review, so anywhere it stands in for my
    # own words it hands a recommender my opinions a second time, where they read as
    # independent corroboration rather than the echo they are.
    synopsis_markdown = models.TextField(
        "Synopsis (LLM)",
        blank=True,
        help_text="Optional. Markdown. Plot orientation for someone who has not read "
        "the book. Never quoted anywhere the site speaks for me.",
    )

    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Columns for later slices ------------------------------------------
    # Behaviour lands in P2/P3; the columns exist now so those slices don't need a
    # schema migration against a live table.
    mastodon_status_id = models.CharField(max_length=64, null=True, blank=True, unique=True)
    mastodon_posted_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self) -> str:
        return f"{self.book.title} ({self.get_status_display()})"

    # -- invariants ---------------------------------------------------------

    def save(self, *args, **kwargs):
        if self.slug == "":
            # "" would collide across drafts under the unique index; NULL does not.
            self.slug = None

        if self.is_published:
            if not self.published_at:
                self.published_at = timezone.now()
            if not self.slug:
                self.slug = self.build_slug()
        # Note the absence of an else-branch: unpublishing never clears the slug or
        # published_at. Re-publishing must land on the same URL that was federated.

        if (update_fields := kwargs.get("update_fields")) is not None:
            kwargs["update_fields"] = set(update_fields) | {"slug", "published_at", "updated_at"}
        super().save(*args, **kwargs)

    def build_slug(self) -> str:
        base = slugify(f"{self.book.title} {self.book.primary_author}")[:180] or "review"
        candidate, n = base, 1
        others = Review.objects.exclude(pk=self.pk)
        while others.filter(slug=candidate).exists():
            n += 1
            candidate = f"{base}-{n}"
        return candidate

    def get_absolute_path(self) -> str:
        return f"/reviews/{self.slug}" if self.slug else ""

    # -- derived ------------------------------------------------------------

    @property
    def is_published(self) -> bool:
        return self.status == self.Status.PUBLISHED

    @property
    def stars_overall(self) -> float:
        return self.rating_overall / 2

    @property
    def stars_narration(self) -> float | None:
        return self.rating_narration / 2 if self.rating_narration else None

    @property
    def body_html(self) -> str:
        return render_markdown(self.body_markdown)

    @property
    def synopsis_html(self) -> str:
        return render_markdown(self.synopsis_markdown)

    @property
    def card_description(self) -> str:
        """What a share card says when there is no hand-written summary.

        A rating on its own is a complete review -- sometimes the stars are the whole
        verdict -- but a card with a blank body under the title reads as broken, and
        that card is how the site reaches anyone at all. So: the summary if it exists,
        else the opening of the body, else the rating stated plainly.

        Computed here rather than in the page and again in the toot, so the two can
        never drift and both are reachable from a test.

        `synopsis_markdown` is not in this chain and must not be added to it. It would
        fill the blank card, which is the temptation -- but it would put a machine's
        paraphrase of my review under my name in an og:description and a toot.
        """
        if self.summary.strip():
            return self.summary.strip()

        excerpt = summarise_markdown(self.body_markdown, CARD_DESCRIPTION_CHARS)
        if excerpt:
            return excerpt

        # No title here on purpose. Everywhere this lands -- og:description under
        # og:title, the toot under its header -- the title is already on the line
        # above, and a card that says the same thing twice reads as a template that
        # went wrong.
        parts = [f"{self.stars_overall:g} out of 5 stars"]
        if self.rating_narration:
            parts.append(f"narration {self.stars_narration:g}")
        return ", ".join(parts)


class ReviewViewDay(models.Model):
    """One row per review per day. The only thing about a visit that is ever stored.

    Deliberately not a log of visits: there is no timestamp finer than the date, no
    address, no user agent, nothing joinable back to a person. The dedup hash lives in
    the cache for six hours and is never written here -- which is exactly what the
    privacy notice on /legal promises, so this model must not grow columns.
    """

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="view_days")
    date = models.DateField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["review", "date"], name="unique_review_day")
        ]
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.review.slug} {self.date}: {self.count}"
