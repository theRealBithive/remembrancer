from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.urls import path, reverse
from django.utils.html import format_html

from catalog.abs import AbsError
from catalog.models import Book
from catalog.profile import build_profile, profile_stats
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
    """A mirror, so effectively read-only: the next sync would discard any edit.

    `hide_from_public` is the single exception, and only because `sync.MIRRORED_FIELDS`
    deliberately omits it.
    """

    list_display = ("thumb", "title", "authors", "narrators", "listening", "write_review",
                    "hide_from_public", "is_orphaned", "synced_at")
    list_display_links = ("title",)
    # The one editable column. Hiding the book you are listening to has to be a tick on
    # the row you are already looking at -- a trip into a change form full of read-only
    # fields to reach a single checkbox is the kind of friction that means it never
    # happens in time.
    list_editable = ("hide_from_public",)
    list_filter = (ReviewedFilter, "is_finished", "is_orphaned", "series")
    search_fields = ("title", "subtitle", "authors", "narrators", "asin", "isbn")
    ordering = ("-finished_at", "title")
    actions = ["sync_now"]
    change_list_template = "admin/catalog/book/change_list.html"

    def get_urls(self):
        return [
            path(
                "export-profile/",
                # admin_view() enforces staff + active + never-cache. This hands out
                # one person's entire reading history; it is not a public page.
                self.admin_site.admin_view(self.export_profile),
                name="catalog_book_export_profile",
            ),
            *super().get_urls(),
        ]

    def export_profile(self, request):
        """The whole library as text, for pasting into an LLM.

        Served inline rather than as a download: the point is to select it and paste
        it somewhere, and a file in ~/Downloads is one step further from that.
        """
        if not self.has_view_permission(request):
            raise PermissionDenied
        compact = request.GET.get("compact") == "1"
        body = build_profile(include_unstarted=not compact)
        response = HttpResponse(body, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = 'inline; filename="listening-profile.txt"'
        # Nothing in between has any business keeping a copy.
        response["Cache-Control"] = "no-store"
        return response

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, {**(extra_context or {}), **profile_stats()})

    def get_queryset(self, request):
        # The review column touches obj.review on every row; without this a 450-book
        # changelist issues a query per row.
        return super().get_queryset(request).select_related("review")

    def get_readonly_fields(self, request, obj=None):
        # Everything except the one field the sync does not own.
        return [f.name for f in Book._meta.fields if f.name != "hide_from_public"]

    def has_add_permission(self, request):
        return False

    @admin.display(description="")
    def thumb(self, obj):
        if not obj.cover_thumb:
            return "—"
        return format_html('<img src="{}" style="height:44px;border-radius:2px">',
                           obj.cover_thumb.url)

    @admin.display(description="review")
    def write_review(self, obj):
        """Start the review from the book you are looking at.

        The other direction -- open the review form and hunt for the book -- means
        scrolling a select of every book in the library, which stops being usable
        somewhere around the fiftieth.
        """
        if review := getattr(obj, "review", None):
            url = reverse("admin:reviews_review_change", args=[review.pk])
            label = "edit" if review.is_published else "finish draft"
            return format_html('<a href="{}">{}</a>', url, label)
        url = reverse("admin:reviews_review_add")
        return format_html('<a class="addlink" href="{}?book={}">write</a>', url, obj.pk)

    def get_search_results(self, request, queryset, search_term):
        """Keep the review form's book autocomplete to books that can still take one.

        Without this the picker happily offers books that already have a review, and
        the only feedback is a validation error after you have typed everything else.
        """
        queryset, may_have_duplicates = super().get_search_results(
            request, queryset, search_term
        )
        if request.GET.get("model_name") == "review" and request.GET.get("field_name") == "book":
            queryset = queryset.filter(review__isnull=True, is_orphaned=False)
        return queryset, may_have_duplicates

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
