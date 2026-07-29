"""A listening profile you can paste into an LLM and ask for a recommendation.

The design constraint is the context window, so the format is terse by construction:
one line per book, a legend at the top instead of repeated field names, and no JSON
punctuation. Everything here is already on your own screen in the admin -- this only
arranges it so a model can read the whole library at once.

What earns its place is signal about taste. A rating is the obvious one; pace is the
quieter one, and often better, because how fast a book went down is a verdict you
gave without meaning to. Abandonment is the strongest negative signal there is.
Publisher, ISBN, cover and ABS ids are omitted: they cost tokens and tell a
recommender nothing.

Dates *are* here, unlike on the public site, where Decision 21 publishes the pace and
withholds the calendar. That rule protects a reader from a listening diary. This file
is one person's entire reading history behind `admin_view()` and `no-store`, handed
deliberately to a model -- there is no diary left to protect, and without a rough date
a recommender cannot tell a taste you had at twenty from the one you have now.
"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from catalog.models import (
    ABANDONED_IDLE_DAYS,
    ABANDONED_MAX_PROGRESS,
    Book,
)

LEGEND = f"""\
LISTENING PROFILE — exported {{today}} from Audiobookshelf via Remembrancer

Format: one book per line. Fields are separated by " | " and the trailing part is
always "Title — Author, read by Narrator (year, runtime)". A run of "> " lines is
my own review of that book, in full. Some books have a rating and no words at all;
that is a rating I stand behind, not a missing review.

  reader  who read it, named wherever I actually heard it. This is audio: a
          narrator is a reason to pick a book up and a reason to put one down.
          A reader recurring above 4 stars is a real preference, worth
          recommending on. The unstarted pile omits it -- unheard.
  stars   my rating, 0.5–5.
  ORM     the strongest positive signal in this document, and rare -- expect a
          handful in the whole library, never most of the 5s. Borrowed from
          Walter Moers: the Orm is the force said to run through a writer when
          the work is more than well made. It is NOT a sixth star and does not
          follow from the rating; it is a separate axis. A flawless book can
          lack it and a flawed one can have it. Read it as: this book did
          something to me. Weight it far above stars. Its absence means only
          "good, and no more than good" -- never a complaint.
  pace    hours of audio per calendar day while I was reading it. High means I
          devoured it; below ~0.5 means I slogged. It is the honest signal --
          I gave it without meaning to. But see "comfort" before you trust it.
  comfort a second, separate appetite: what I put on to switch off. Pace is a
          liar here -- these go down fast because they ask nothing of me, not
          because they moved me. Recommend WITHIN this set if I ask for it,
          but never average it together with everything else. Treated as one
          taste it produces recommendations that match nothing I actually want.
  dropped started it, got under {ABANDONED_MAX_PROGRESS:.0%} in, and never went back for
          {ABANDONED_IDLE_DAYS}+ days. Read this as a strong negative.
  why:    on a dropped book, why I stopped. The distinction that matters:
          "wrong moment" means keep suggesting this kind of thing, "not for
          me" means stop. Do not read every abandonment as the same verdict.
  finished / last touched
          year and month, for trajectory: what I read five years ago and what
          I read now are different answers. A book "in progress" but last
          touched a year ago is one I gave up on without admitting it.

Sections are ordered by how much they say about my taste. Everything listed is
already in my library, so recommend books that appear nowhere below.
"""


def _runtime(book: Book) -> str:
    if not book.duration_seconds:
        return ""
    hours = book.duration_seconds / 3600
    return f"{hours:.0f}h" if hours >= 1 else f"{book.duration_seconds // 60}m"


def _title(book: Book, *, narrator: bool = True) -> str:
    """`Title — Author, read by Narrator (year, runtime)`, empty parts left out.

    `narrator=False` for the to-read pile. That section is most of the file and says
    only "already owned"; naming a reader I have never heard is pure cost, and cutting
    it there is what pays for the reader appearing everywhere it means something.
    """
    line = book.title
    if book.series:
        line += f" [{book.series}"
        line += f" #{book.series_sequence}]" if book.series_sequence else "]"
    if book.authors:
        line += f" — {book.authors}"
    if narrator and book.narrators:
        line += f", read by {book.narrators}"

    facts = [str(book.published_year) if book.published_year else "", _runtime(book)]
    facts = [f for f in facts if f]
    return f"{line} ({', '.join(facts)})" if facts else line


def _pace(book: Book) -> str:
    pace = book.listening_pace
    return f"pace {pace:.1f}" if pace is not None else "pace ?"


def _month(when) -> str:
    """`2026-03`. The day is a diary; the month is a trajectory."""
    return timezone.localtime(when).strftime("%Y-%m") if when else ""


def _when(book: Book) -> list[str]:
    """When it was finished, or when it was last opened.

    Absent upstream on plenty of books, exactly like pace, so it is omitted silently
    rather than printed as a question mark -- one "?" per line is enough.
    """
    if book.is_finished:
        stamp = _month(book.finished_at)
        return [f"finished {stamp}"] if stamp else []
    stamp = _month(book.last_played_at)
    return [f"last touched {stamp}"] if stamp else []


def _comfort(book: Book) -> list[str]:
    return ["comfort"] if book.is_comfort_read else []


def _verdict(review) -> list[str]:
    """The whole review, every line prefixed with "> ".

    The summary alone is written for a Mastodon card, not for a recommender -- the
    reasons live in the body. Quoting both the same way costs a character a line and
    makes it unambiguous where one book's words stop and the next book's begin.
    """
    blocks = [b for b in (review.summary.strip(), review.body_markdown.strip()) if b]
    if not blocks:
        return []  # stars only. The rating line above already said everything there is.
    return [f"> {line}".rstrip() for line in "\n\n".join(blocks).splitlines()]


def _reviewed_lines(books) -> list[str]:
    lines = []
    for book in books:
        review = book.review
        parts = [f"{review.stars_overall:g} stars"]
        # Second, right after the rating it is meant to be read against, and in caps
        # so it cannot be skimmed past in a wall of lowercase fields.
        if review.had_orm:
            parts.append("ORM")
        if review.rating_narration:
            parts.append(f"narration {review.stars_narration:g}")
        if book.is_finished:
            parts.append(_pace(book))
        elif book.is_abandoned:
            parts.append("dropped")
        # A comfort read that earned a review keeps its place here -- the review is
        # real taste data wherever it came from -- but still says what it is.
        parts += _comfort(book) + _when(book)
        lines.append(f"{' | '.join(parts)} | {_title(book)}")
        verdict = _verdict(review)
        if verdict:
            lines.extend(verdict)
            lines.append("")  # or a long review runs straight into the next title
    return lines


def _progress(book: Book) -> str:
    """`0% in` reads as "not started", which is the opposite of what it means."""
    return f"{book.progress:.0%} in" if book.progress >= 0.01 else "barely started"


def _dropped_lines(book: Book) -> list[str]:
    minutes = round((book.seconds_listened or 0) / 60)
    parts = [f"dropped, {_progress(book)}, after {minutes}m", *_comfort(book), *_when(book)]
    lines = [f"{' | '.join(parts)} | {_title(book)}"]
    if book.abandoned_note.strip():
        # Indented on its own line rather than appended to the fields: it is a
        # sentence, and a sentence inside a " | " run stops the row being scannable.
        lines.append(f"  why: {book.abandoned_note.strip()}")
    return lines


def build_profile(*, include_unstarted: bool = True) -> str:
    """Render the whole library as text.

    `include_unstarted` is the one size dial that matters: the to-read pile is
    usually most of the library and contributes nothing but "don't suggest this".
    Worth its tokens when you want the recommendation to be new, not otherwise.
    """
    # Orphans are out, with one exception: a book I reviewed stays in even after it
    # vanishes from Audiobookshelf. The verdict was mine, and it still describes my
    # taste whether or not the file is still on the server.
    books = (
        Book.objects.filter(Q(is_orphaned=False) | Q(review__isnull=False))
        .select_related("review")
        .order_by("title")
    )

    reviewed = sorted(
        (b for b in books if getattr(b, "review", None)),
        key=lambda b: -b.review.rating_overall,
    )
    rest = [b for b in books if not getattr(b, "review", None)]
    finished = sorted(
        (b for b in rest if b.is_finished),
        key=lambda b: -(b.listening_pace or 0),
    )
    dropped = [b for b in rest if not b.is_finished and b.is_abandoned]
    started = [
        b for b in rest if not b.is_finished and not b.is_abandoned and b.progress > 0
    ]
    unstarted = [
        b for b in rest if not b.is_finished and not b.is_abandoned and not b.progress
    ]

    out = [LEGEND.format(today=timezone.localdate().isoformat())]

    def section(title: str, items, render):
        if not items:
            return  # an empty heading is a line of context spent saying nothing
        out.append(f"== {title} ({len(items)}) ==")
        out.extend(render(items))
        out.append("")

    def fields(book: Book, *lead: str) -> str:
        return " | ".join([*lead, *_comfort(book), *_when(book), _title(book)])

    section("REVIEWED — my verdict in my own words", reviewed, _reviewed_lines)
    section(
        "FINISHED, NOT YET REVIEWED — I stayed to the end",
        finished,
        lambda bs: [fields(b, _pace(b)) for b in bs],
    )
    section(
        "ABANDONED — started and gave up",
        dropped,
        lambda bs: [line for b in bs for line in _dropped_lines(b)],
    )
    section(
        "IN PROGRESS",
        started,
        lambda bs: [fields(b, _progress(b)) for b in bs],
    )
    if include_unstarted:
        section(
            "UNSTARTED, ALREADY OWNED — do not recommend these",
            unstarted,
            # No reader here: see `_title`. This section is the bulk of the file and
            # exists only to say "already owned".
            lambda bs: [_title(b, narrator=False) for b in bs],
        )
    else:
        # Deliberately still says how many: "recommend me something new" is a weaker
        # request if the model cannot tell whether the pile is five books or four
        # hundred. Worth the one line it costs.
        out.append(f"({len(unstarted)} unstarted books in the library, omitted.)\n")

    out.append(
        "Given the above, recommend audiobooks I do not already own. Say which "
        "specific things in my history each one follows from, and include at least "
        "one that is a deliberate departure from the pattern. Where anything is "
        "marked ORM, treat that as the clearest statement of what I actually want "
        "more of. Leave the lines marked `comfort` out of that reasoning entirely "
        "unless I ask for more of them. Name the reader where the edition matters."
    )
    return "\n".join(out) + "\n"


def profile_stats() -> dict[str, int]:
    """Counts for the admin, so the button can say what it is about to hand you."""
    live = Book.objects.filter(Q(is_orphaned=False) | Q(review__isnull=False))
    return {
        "reviewed": live.filter(review__isnull=False).count(),
        "finished": live.filter(is_finished=True, review__isnull=True).count(),
        "abandoned": live.filter(Book.abandoned_q(), review__isnull=True).count(),
        "comfort": live.filter(is_comfort_read=True).count(),
        "unstarted": live.filter(
            Q(progress=0) | Q(progress__isnull=True), is_finished=False
        ).count(),
    }
