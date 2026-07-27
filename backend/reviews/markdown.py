"""Markdown rendering with a hard sanitization step.

Single-author is not a reason to skip sanitizing (Decision 6). The rendered output
is injected into the page with dangerouslySetInnerHTML on the Next side, so this
function is the only thing standing between the DB and stored XSS -- if the admin
session is ever compromised, or a future slice accepts input from anywhere else,
this is the control that still holds.
"""

from __future__ import annotations

import html
import re

import nh3
from markdown_it import MarkdownIt

# `zero` + explicit enables: an allowlist of syntax rather than a denylist. Notably
# html_inline/html_block stay off, so raw HTML in the source is escaped, not parsed.
_md = (
    MarkdownIt("zero", {"linkify": True, "typographer": True})
    .enable([
        "table", "list", "blockquote", "code", "fence", "heading", "hr", "emphasis",
        "link", "linkify", "newline", "paragraph", "strikethrough", "backticks",
        "escape", "entity", "smartquotes", "replacements",
    ])
)

ALLOWED_TAGS = {
    "p", "br", "hr", "em", "strong", "del", "blockquote", "code", "pre",
    "ul", "ol", "li", "a", "h2", "h3", "h4", "table", "thead", "tbody", "tr", "th", "td",
}
# "rel" is deliberately absent: nh3 refuses to allow it alongside link_rel, and
# link_rel is the stronger option because nh3 then sets it on every link itself.
ALLOWED_ATTRIBUTES = {"a": {"href", "title"}}
ALLOWED_SCHEMES = {"http", "https", "mailto"}


def render_markdown(text: str) -> str:
    if not text or not text.strip():
        return ""
    return nh3.clean(
        _md.render(text),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_SCHEMES,
        link_rel="nofollow noopener noreferrer",
    )


def summarise_markdown(text: str, limit: int) -> str:
    """Plain-text opening of a Markdown document, for a share card.

    Goes through `render_markdown` first rather than regexing the source: the renderer
    already knows what a link, a heading and a code fence are, and reusing it means the
    excerpt can never contain syntax the page does not also strip.

    Truncation prefers a sentence end, then a word end, and only cuts mid-word if the
    text offers neither -- a card ending on half a word looks like a bug.
    """
    if not text or not text.strip():
        return ""

    plain = html.unescape(nh3.clean(render_markdown(text), tags=set(), attributes={}))
    plain = re.sub(r"\s+", " ", plain).strip()
    if len(plain) <= limit:
        return plain

    window = plain[: limit + 1]
    sentence = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if sentence >= limit // 2:
        return window[: sentence + 1]

    space = window.rfind(" ")
    return (window[:space] if space > 0 else plain[:limit]).rstrip(" ,;:—-") + "…"
