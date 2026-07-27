"""The entire write path (Decision 7).

Kept inside Django's session auth on purpose: CSRF, password hashing, and axes
throttling all apply here for free, and Next.js exposes no mutating endpoint at all.
"""

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.utils.html import format_html
from django_q.tasks import async_task

from catalog.models import Book
from reviews.mastodon import configured as mastodon_configured
from reviews.models import Review, ReviewViewDay


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        # Explicit allowlist rather than "__all__": slug, published_at, view_count and
        # the mastodon_* columns are derived or machine-owned and must never be
        # settable from a form post, even by staff.
        fields = ("book", "status", "rating_overall", "rating_narration",
                  "summary", "body_markdown")
        widgets = {
            "summary": forms.Textarea(attrs={"rows": 3, "cols": 80}),
            "body_markdown": forms.Textarea(attrs={"rows": 26, "cols": 100,
                                                   "style": "font-family:ui-monospace,monospace"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # One review per book (Decision 19): only offer books that don't have one.
        available = Book.objects.filter(review__isnull=True, is_orphaned=False)
        if self.instance.pk:
            available = available | Book.objects.filter(pk=self.instance.book_id)
        self.fields["book"].queryset = available.order_by("-finished_at", "title")


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    form = ReviewForm
    list_display = ("book_title", "rating_display", "status", "published_at",
                    "syndication", "view_count")
    list_filter = ("status",)
    actions = ["post_to_mastodon"]
    search_fields = ("book__title", "book__authors", "summary", "body_markdown")
    date_hierarchy = "published_at"
    # A searchable picker rather than a select holding every book in the library.
    # BookAdmin.get_search_results narrows it to books without a review.
    autocomplete_fields = ("book",)
    readonly_fields = ("slug", "published_at", "view_count", "mastodon_status_id",
                       "mastodon_posted_at", "public_link", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("book", "status", "public_link")}),
        ("Rating", {"fields": ("rating_overall", "rating_narration"),
                    "description": "Half-steps: 1–10 renders as 0.5–5 stars."}),
        ("Review", {"fields": ("summary", "body_markdown"),
                    "description": "Both optional. A rating on its own is a complete "
                                   "review; the share card falls back to the body, "
                                   "then to the stars."}),
        ("Published state", {
            "classes": ("collapse",),
            "fields": ("slug", "published_at", "view_count",
                       "mastodon_status_id", "mastodon_posted_at",
                       "created_at", "updated_at"),
            "description": "The slug is assigned at first publish and then frozen — "
                           "a federated link must never 404.",
        }),
    )

    @admin.display(description="book", ordering="book__title")
    def book_title(self, obj):
        return obj.book.title

    @admin.display(description="rating")
    def rating_display(self, obj):
        narration = f" · narration {obj.stars_narration:g}★" if obj.rating_narration else ""
        return f"{obj.stars_overall:g}★{narration}"

    @admin.display(description="mastodon")
    def syndication(self, obj):
        if not obj.mastodon_status_id:
            return "—"
        return format_html('<span title="{}">posted</span>', obj.mastodon_posted_at or "")

    @admin.action(description="Post to Mastodon")
    def post_to_mastodon(self, request, queryset):
        """Queue syndication. Deliberately separate from publishing (Decision 9).

        Skipping is reported per review rather than silently: an action that says
        nothing about the three it ignored trains you to assume it worked.
        """
        if not mastodon_configured():
            self.message_user(
                request, "MASTODON_BASE_URL/MASTODON_TOKEN are not set.", messages.ERROR
            )
            return

        queued, skipped = [], []
        for review in queryset.select_related("book"):
            if review.mastodon_status_id:
                skipped.append(f"{review.book.title} (already posted)")
            elif not review.is_published:
                skipped.append(f"{review.book.title} (not published)")
            else:
                # The real guard is inside the task, under select_for_update -- these
                # checks only avoid queueing work that is certain to be refused.
                async_task("reviews.tasks.post_review_to_mastodon", review.pk,
                           task_name=f"mastodon-{review.pk}")
                queued.append(review.book.title)

        if queued:
            self.message_user(
                request,
                f"Queued {len(queued)}: {', '.join(queued)}. Watch the qcluster log; "
                "the Mastodon column fills in once it lands.",
                messages.SUCCESS,
            )
        if skipped:
            self.message_user(request, f"Skipped {len(skipped)}: {'; '.join(skipped)}",
                              messages.WARNING)

    @admin.display(description="public page")
    def public_link(self, obj):
        if not obj.slug:
            return "— not published yet"
        url = f"{settings.SITE_URL}{obj.get_absolute_path()}"
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, url)


@admin.register(ReviewViewDay)
class ReviewViewDayAdmin(admin.ModelAdmin):
    """Read-only. The numbers are written by the beacon; editing them would only
    let you lie to yourself."""

    list_display = ("date", "review", "count")
    list_filter = ("date",)
    search_fields = ("review__book__title",)
    date_hierarchy = "date"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
