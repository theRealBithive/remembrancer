/**
 * The Orm mark, and the note that explains it.
 *
 * Borrowed from Walter Moers' Zamonien novels: the Orm is the force said to run
 * through a writer when the work is more than well made. It is a second axis, not a
 * sixth star -- a flawless book can lack it and a flawed one can carry it -- so it is
 * set beside the scores rather than drawn as one.
 *
 * The word, never a glyph. A rune or an asterisk next to a number reads as decoration,
 * or as a footnote about the number; the word is the one form a stranger can look up,
 * and the note below gives them somewhere to land without leaving the page.
 */

const ANCHOR = "orm";

const LABEL =
  "font-mono text-[0.65rem] uppercase tracking-[0.16em] text-muted " +
  "underline decoration-rule decoration-1 underline-offset-4 hover:decoration-ink";

/**
 * Set as a peer of `Score`: same display face, same size, same label beneath. It is
 * part of the verdict, so it is typeset like the rest of the verdict -- a small mark
 * tucked beside two large numerals would read as a footnote marker on the rating,
 * which is the one thing it must not be mistaken for.
 */
export function OrmScore() {
  return (
    <div>
      <p className="font-display text-3xl leading-none sm:text-4xl">
        Orm
        <span className="sr-only"> — this one did something to me.</span>
      </p>
      <a href={`#${ANCHOR}`} className={`mt-2 block ${LABEL}`}>
        What this means
      </a>
    </div>
  );
}

/**
 * The compact form, for a list row. Not an anchor: on the index every row is already
 * wrapped in a Link, and an anchor inside an anchor is invalid HTML that browsers
 * repair by splitting the outer one.
 */
export function OrmMark() {
  return (
    <span className="mt-1 block font-display text-xl leading-none sm:text-2xl">
      Orm
      <span className="sr-only"> — this one did something to me</span>
    </span>
  );
}

/**
 * Rendered once per page, and only where a mark above it points. A standing footnote
 * under a list with no marked book in it explains an absence nobody asked about.
 */
export function OrmNote() {
  return (
    <aside
      id={ANCHOR}
      aria-label="About the Orm mark"
      className="mt-16 max-w-[var(--measure)] border-t border-rule pt-5 text-sm text-muted"
    >
      <p>
        <span className="font-display text-base text-ink">Orm</span> — borrowed from
        Walter Moers, who describes it as the force that runs through a writer when the
        work is more than well made. It is not a sixth star and does not follow from the
        rating: a flawless book can lack it, and a flawed one can carry it. It marks the
        books that did something to me. Most did not, and that is no complaint against
        them.
      </p>
    </aside>
  );
}
