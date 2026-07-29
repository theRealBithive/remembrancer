"""Atom feed at /feed.xml.

Django's syndication framework rather than hand-written XML. Rendered dynamically by
Django (Caddy routes this one path here), so unlike the Next pages there is nothing
to revalidate on publish -- feed readers poll.
"""

from django.conf import settings
from django.contrib.syndication.views import Feed
from django.utils.feedgenerator import Atom1Feed

from reviews.api import published


class ReviewsFeed(Feed):
    feed_type = Atom1Feed
    title = f"{settings.SITE_NAME} — audiobook reviews"
    subtitle = "Ratings and reviews of what I've been listening to."

    # Methods, not class attributes: an attribute would bind SITE_URL at import time.
    # Absolute on purpose -- given a relative value the syndication framework prepends
    # the django.contrib.sites domain, which defaults to example.com and would ship a
    # feed whose every link points somewhere that isn't this site.
    def link(self, obj):
        return settings.SITE_URL

    def feed_url(self, obj):
        return f"{settings.SITE_URL}/feed.xml"

    def items(self):
        return published()[:50]

    def item_title(self, item):
        # Spelled out rather than a glyph: a reader shows this as plain text with no
        # page around it to explain a mark, so the word has to survive on its own.
        marks = f"{item.stars_overall:g}★" + (", Orm" if item.had_orm else "")
        return f"{item.book.title} — {item.book.primary_author} ({marks})"

    def item_description(self, item):
        # Never empty: a rating-only review still has to be a readable row in a reader,
        # and `card_description` states the stars when there are no words.
        return item.body_html or item.summary or item.card_description

    def item_link(self, item):
        return f"{settings.SITE_URL}{item.get_absolute_path()}"

    def item_pubdate(self, item):
        return item.published_at

    def item_updateddate(self, item):
        return item.updated_at
