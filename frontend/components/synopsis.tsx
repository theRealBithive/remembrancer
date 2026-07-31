/**
 * The plot summary, folded away.
 *
 * A review is written for someone who has read the book. A stranger arriving from a
 * link usually has not, and the page gave them nowhere to get their bearings. This is
 * that — and it is written by a model, not by me, which is why it is both collapsed
 * and labelled as such rather than quietly set in the same type as everything else.
 *
 * Closed by default because the reader it is not for is the more common one, and
 * because an unasked-for plot summary above a review reads as the site explaining the
 * book to you before you are allowed the opinion. Native <details>: no script, no
 * hydration, and it still opens with JavaScript off.
 */

export function Synopsis({ html }: { html: string }) {
  return (
    // A sibling of the body's .prose, never a child: `.prose > * + *` sets the flow
    // spacing and would lay the <summary> out as a paragraph of the review.
    //
    // No rule of its own. The page already draws one directly above this, and two
    // parallel lines with a gap between them read as a mistake rather than a
    // boundary; the label's own underline is enough to mark it as a control.
    <details className="mt-9 max-w-[var(--measure)]">
      <summary
        className="cursor-pointer list-none font-mono text-[0.65rem] uppercase
                   tracking-[0.16em] text-muted underline decoration-rule decoration-1
                   underline-offset-4 hover:decoration-ink
                   [&::-webkit-details-marker]:hidden"
      >
        Synopsis — skip if you already read the book (most likely LLM generated)
      </summary>
      <div
        // Size and colour both live in `.prose-muted`, not in utilities here: `.prose`
        // is unlayered CSS and would win against a layered `text-base`.
        className="prose prose-muted mt-5"
        // Sanitized server-side by nh3 before it ever leaves Django (reviews/markdown.py),
        // by the same call that renders the review body.
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </details>
  );
}
