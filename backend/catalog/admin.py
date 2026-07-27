from django.contrib import admin, messages
from django.utils.html import format_html

from catalog.abs import AbsError
from catalog.models import Book
from catalog.sync import sync


def humanize_days(days: float) -> str:
    if days < 1:
        return "same day"
    if days < 2:
        return "1 day"
    if days < 60:
        return f"{round(days)} days"
    if days < 365:
        return f"{days / 30.44:.0f} months"
    return f"{days / 365.25:.1f} years"


class ReviewedFilter(admin.SimpleListFilter):
    """The queue, in two buckets.

    Abandonment is a verdict too -- "I bailed twenty minutes in" is a review worth
    writing -- so a dropped book earns a place in the queue rather than vanishing
    from it just because it was never finished.
    """

    title = "review state"
    parameter_name = "reviewed"

    def lookups(self, request, model_admin):
        return [
            ("queue", "Finished, awaiting review"),
            ("abandoned", "Abandoned, awaiting review"),
            ("yes", "Reviewed"),
            ("no", "No review"),
        ]

    def queryset(self, request, queryset):
        match self.value():
            case "queue":
                return queryset.filter(is_finished=True, review__isnull=True, is_orphaned=False)
            case "abandoned":
                return queryset.filter(Book.abandoned_q(), review__isnull=True)
            case "yes":
                return queryset.filter(review__isnull=False)
            case "no":
                return queryset.filter(review__isnull=True)
        return queryset


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    """Read-only: this table is a mirror, and the next sync would discard any edit."""

    list_display = ("thumb", "title", "authors", "narrators", "listening", "has_review",
                    "is_orphaned", "synced_at")
    list_display_links = ("title",)
    list_filter = (ReviewedFilter, "is_finished", "is_orphaned", "series")
    search_fields = ("title", "subtitle", "authors", "narrators", "asin", "isbn")
    ordering = ("-finished_at", "title")
    actions = ["sync_now"]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in Book._meta.fields]

    def has_add_permission(self, request):
        return False

    @admin.display(description="")
    def thumb(self, obj):
        if not obj.cover_thumb:
            return "—"
        return format_html('<img src="{}" style="height:44px;border-radius:2px">',
                           obj.cover_thumb.url)

    @admin.display(boolean=True, description="reviewed")
    def has_review(self, obj):
        return hasattr(obj, "review")

    @admin.display(description="listening")
    def listening(self, obj):
        """The rating hint: how fast it went down, or how hard it was dropped."""
        if obj.is_finished:
            days, pace = obj.days_to_finish, obj.listening_pace
            if days is None or pace is None:
                return "finished"
            return format_html(
                '<span title="{} h of audio over {} days">{} · {} h/day</span>',
                round((obj.duration_seconds or 0) / 3600, 1), round(days, 1),
                humanize_days(days), round(pace, 1),
            )
        if obj.is_abandoned:
            minutes = round((obj.seconds_listened or 0) / 60)
            return format_html('<span style="color:#b03030">dropped after {} min</span>', minutes)
        if obj.progress:
            return f"{obj.progress:.0%} in"
        return "—"

    @admin.action(description="Sync now from Audiobookshelf")
    def sync_now(self, request, queryset):
        """Full sync -- the selection is ignored; ABS is the source of truth."""
        try:
            report = sync()
        except AbsError as exc:
            self.message_user(request, f"Sync failed: {exc}", messages.ERROR)
            return
        level = messages.WARNING if report.cover_errors else messages.SUCCESS
        self.message_user(request, f"Sync complete — {report}", level)
