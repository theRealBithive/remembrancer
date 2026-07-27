"""The entire write path (Decision 7).

Kept inside Django's session auth on purpose: CSRF, password hashing, and axes
throttling all apply here for free, and Next.js exposes no mutating endpoint at all.
"""

from django import forms
from django.conf import settings
from django.contrib import admin
from django.utils.html import format_html

from catalog.models import Book
from reviews.models import Review


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
    list_display = ("book_title", "rating_display", "status", "published_at", "view_count")
    list_filter = ("status",)
    search_fields = ("book__title", "book__authors", "summary", "body_markdown")
    date_hierarchy = "published_at"
    autocomplete_fields = ()
    readonly_fields = ("slug", "published_at", "view_count", "mastodon_status_id",
                       "mastodon_posted_at", "public_link", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("book", "status", "public_link")}),
        ("Rating", {"fields": ("rating_overall", "rating_narration"),
                    "description": "Half-steps: 1–10 renders as 0.5–5 stars."}),
        ("Review", {"fields": ("summary", "body_markdown")}),
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

    @admin.display(description="public page")
    def public_link(self, obj):
        if not obj.slug:
            return "— not published yet"
        url = f"{settings.SITE_URL}{obj.get_absolute_path()}"
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, url)
