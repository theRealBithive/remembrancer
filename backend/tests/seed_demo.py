"""Seed a local sqlite DB with demo data for manual and end-to-end checks.

    uv run manage.py shell < tests/seed_demo.py

Not imported by the test suite -- pytest builds its own fixtures.
"""

import io
from datetime import datetime, timedelta

from django.utils import timezone
from PIL import Image, ImageDraw

from catalog.models import Book, normalize_match_key
from catalog.sync import store_cover
from reviews.models import Review

DEMO = [
    {
        "abs_item_id": "demo-phm",
        "title": "Project Hail Mary",
        "authors": "Andy Weir",
        "narrators": "Ray Porter",
        "published_year": 2021,
        "duration_seconds": 16 * 3600 + 10 * 60,
        "colour": (196, 92, 47),
        "days": 3.0,   # devoured
        "rating_overall": 9,
        "rating_narration": 10,
        # The one marked entry, so the mark and its footnote are both exercised and a
        # 4.5 sitting next to it proves the two axes really are independent.
        "had_orm": True,
        "summary": "Ray Porter doesn't narrate this so much as inhabit it. The best "
                   "argument I know for listening to a book instead of reading it.",
        "body": (
            "The premise is silly and the physics is load-bearing, which is the exact "
            "ratio Weir is good at.\n\n"
            "What makes the *audio* edition worth choosing is Porter's handling of "
            "Rocky. A lesser reader plays it for novelty. Porter plays it straight, and "
            "by the midpoint you stop noticing that one half of the conversation isn't "
            "human.\n\n"
            "> Sixteen hours, and I resented every interruption."
        ),
    },
    {
        "abs_item_id": "demo-piranesi",
        "title": "Piranesi",
        "authors": "Susanna Clarke",
        "narrators": "Chiwetel Ejiofor",
        "published_year": 2020,
        "duration_seconds": 6 * 3600 + 45 * 60,
        "colour": (58, 74, 110),
        "days": 12.0,
        "rating_overall": 8,
        "rating_narration": 9,
        "summary": "Short, strange, and quietly devastating. Ejiofor reads it like "
                   "someone describing a dream they're still inside.",
        "body": "A house that is a world. Clarke withholds so patiently that the "
                "reveal lands as grief rather than twist.",
    },
    {
        "abs_item_id": "demo-dune",
        "title": "Dune",
        "authors": "Frank Herbert",
        "narrators": "Simon Vance, Scott Brick",
        "published_year": 1965,
        "duration_seconds": 21 * 3600 + 8 * 60,
        "colour": (176, 142, 70),
        "days": 240.0,  # a crawl -- the other end of the scale
        "rating_overall": 7,
        "rating_narration": 5,
        "summary": "The book endures. This particular production, with its shifting "
                   "cast and uneven levels, does not do it many favours.",
        "body": "Worth it for the text. The full-cast interludes break the spell more "
                "often than they earn it.",
    },
    {
        # Stars and nothing else. Here so the layout is exercised by the case that has
        # no lede paragraph to fill the space under the rating.
        "abs_item_id": "demo-echo",
        "title": "Echopraxia",
        "authors": "Peter Watts",
        "narrators": "Adam J. Rough",
        "published_year": 2014,
        "duration_seconds": 12 * 3600 + 39 * 60,
        "colour": (58, 74, 92),
        "days": 9.0,
        "rating_overall": 7,
        "rating_narration": 8,
        "summary": "",
        "body": "",
    },
    {
        # Unfinished and unreviewed, which is what "now listening" needs. Without one
        # of these the homepage panel has nothing to draw and any assertion on it
        # passes by rendering nothing.
        "abs_item_id": "demo-anathem",
        "title": "Anathem",
        "authors": "Neal Stephenson",
        "narrators": "William Dufris",
        "published_year": 2008,
        "duration_seconds": 32 * 3600 + 27 * 60,
        "colour": (86, 96, 84),
        "in_progress": 0.41,
    },
]


def cover(colour, title):
    image = Image.new("RGB", (400, 600), colour)
    draw = ImageDraw.Draw(image)
    draw.rectangle([20, 20, 380, 580], outline=(255, 255, 255), width=2)
    draw.text((40, 500), title[:22], fill=(255, 255, 255))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def finished_in_month(month: int):
    """Noon on the 12th, in the site's timezone.

    The finished books are spread across the months elapsed so far this year rather
    than pinned to fixed dates, so the year bar has a shape whenever the seed is run
    -- fixed offsets would land in the previous year every January.
    """
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime(timezone.localdate().year, month, 12, 12), tz)


finished = [entry for entry in DEMO if "in_progress" not in entry]
elapsed_months = timezone.localdate().month

for entry in DEMO:
    data = dict(entry)
    colour = data.pop("colour")
    in_progress = data.pop("in_progress", None)

    if in_progress is None:
        days = data.pop("days")
        # Spread over January..this month, oldest entry first.
        position = finished.index(entry)
        month = 1 + round(position * (elapsed_months - 1) / max(len(finished) - 1, 1))
        listening = {
            "is_finished": True,
            "finished_at": (finished_at := finished_in_month(month)),
            "started_at": finished_at - timedelta(days=days),
            "last_played_at": finished_at,
            "progress": 1.0,
            "seconds_listened": data["duration_seconds"],
        }
        review_fields = {
            "rating_overall": data.pop("rating_overall"),
            "rating_narration": data.pop("rating_narration"),
            "had_orm": data.pop("had_orm", False),
            "summary": data.pop("summary"),
            "body_markdown": data.pop("body"),
            "status": Review.Status.PUBLISHED,
        }
    else:
        started = timezone.now() - timedelta(days=6)
        listening = {
            "is_finished": False,
            "finished_at": None,
            "started_at": started,
            "last_played_at": timezone.now() - timedelta(hours=3),
            "progress": in_progress,
            "seconds_listened": int(data["duration_seconds"] * in_progress),
        }
        review_fields = None

    book, _ = Book.objects.update_or_create(
        abs_item_id=data["abs_item_id"],
        defaults={
            **data,
            **listening,
            "match_key": normalize_match_key(data["title"], data["authors"]),
        },
    )
    # Same code path as the real sync, so reseeding replaces cover files instead of
    # accumulating suffixed duplicates in the media volume.
    store_cover(book, cover(colour, data["title"]))
    book.save()

    if review_fields is None:
        print(f"(no review): {book.title} — {book.progress:.0%} in")
        continue

    review, _ = Review.objects.update_or_create(book=book, defaults=review_fields)
    print(f"{review.slug}: {book.title}")
