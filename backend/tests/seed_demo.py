"""Seed a local sqlite DB with demo data for manual and end-to-end checks.

    uv run manage.py shell < tests/seed_demo.py

Not imported by the test suite -- pytest builds its own fixtures.
"""

import io

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
        "rating_overall": 9,
        "rating_narration": 10,
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
        "rating_overall": 7,
        "rating_narration": 5,
        "summary": "The book endures. This particular production, with its shifting "
                   "cast and uneven levels, does not do it many favours.",
        "body": "Worth it for the text. The full-cast interludes break the spell more "
                "often than they earn it.",
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


for entry in DEMO:
    data = dict(entry)
    colour = data.pop("colour")
    rating_overall = data.pop("rating_overall")
    rating_narration = data.pop("rating_narration")
    summary = data.pop("summary")
    body = data.pop("body")

    book, _ = Book.objects.update_or_create(
        abs_item_id=data["abs_item_id"],
        defaults={
            **data,
            "is_finished": True,
            "match_key": normalize_match_key(data["title"], data["authors"]),
        },
    )
    # Same code path as the real sync, so reseeding replaces cover files instead of
    # accumulating suffixed duplicates in the media volume.
    store_cover(book, cover(colour, data["title"]))
    book.save()

    review, _ = Review.objects.update_or_create(
        book=book,
        defaults={
            "rating_overall": rating_overall,
            "rating_narration": rating_narration,
            "summary": summary,
            "body_markdown": body,
            "status": Review.Status.PUBLISHED,
        },
    )
    print(f"{review.slug}: {book.title}")
