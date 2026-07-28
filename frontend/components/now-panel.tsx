import type { Now } from "@/lib/api";
import { runtime } from "@/lib/format";

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/**
 * The shortest month that still reads as a month rather than as "everything". Without
 * it a single book in January draws a full-height rule and the year looks finished.
 */
const MIN_SCALE = 3;

/** The bar's tallest rule, in px. Small enough to sit under a line of mono caps. */
const BAR_HEIGHT = 26;

function Heading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted">
      {children}
    </h2>
  );
}

/**
 * What is on right now. Not a link: there is no review page yet, and a heading that
 * looks clickable and isn't is worse than plain text.
 */
function NowListening({ book }: { book: NonNullable<Now["listening"]> }) {
  const percent = Math.round(book.progress * 100);
  const length = runtime(book.duration_seconds);

  return (
    <section>
      <Heading>Now listening</Heading>

      <div className="mt-3 flex gap-3">
        {book.cover_thumb_url && (
          // eslint-disable-next-line @next/next/no-img-element -- Django emits both
          // sizes at sync time, so the optimizer has nothing to add.
          <img
            src={book.cover_thumb_url}
            alt=""
            width={40}
            height={60}
            loading="lazy"
            className="h-[60px] w-10 shrink-0 object-cover"
          />
        )}
        <div className="min-w-0">
          <p className="font-display text-base leading-tight">{book.title}</p>
          {book.authors && <p className="mt-0.5 text-sm text-muted">{book.authors}</p>}
        </div>
      </div>

      {/* The same idiom as ListeningLine: a hairline that carries a quantity. Here the
          quantity is how far in, so the rule is drawn twice -- the whole book in the
          rule colour, the part heard in ink. */}
      <div className="mt-3 h-px w-full bg-rule" aria-hidden="true">
        <div className="h-px bg-ink" style={{ width: `${percent}%` }} />
      </div>
      <p className="mt-2 font-mono text-[0.65rem] tracking-[0.08em] text-muted">
        {percent}% in{length && <span className="opacity-70"> · {length}</span>}
      </p>
    </section>
  );
}

/**
 * Twelve months as twelve rules. A goal-shaped bar would need a target to fill against
 * and there isn't one; the shape of the year says more than a percentage of a number
 * picked in January.
 */
function YearBar({ year }: { year: Now["year"] }) {
  const { months, total } = year;
  const scale = Math.max(...months, MIN_SCALE);

  return (
    <section>
      <Heading>Books this year</Heading>

      <div
        className="mt-3 flex w-full items-end gap-[3px]"
        style={{ height: BAR_HEIGHT }}
        aria-hidden="true"
      >
        {months.map((count, index) => (
          <span
            key={index}
            title={`${MONTH_NAMES[index]}: ${count}`}
            className={`flex-1 ${
              count === 0 ? "bg-rule" : index === year.month - 1 ? "bg-ink" : "bg-muted"
            }`}
            // A month with nothing in it still draws a hairline, so the year keeps its
            // full width and an empty autumn reads as empty rather than as absent.
            //
            // Square root for the same reason `runtimeFraction` uses one: a single
            // catch-up month of seventeen books would otherwise flatten every ordinary
            // month of four or five into the baseline, and the shape of the year is
            // the entire point of drawing it.
            style={{
              height: count === 0 ? 1 : Math.max(3, Math.sqrt(count / scale) * BAR_HEIGHT),
            }}
          />
        ))}
      </div>

      <p className="mt-2 font-mono text-[0.65rem] tracking-[0.08em] text-muted">
        {total} in {year.year}
      </p>
      {/* The rules are decorative; the sentence is the content. */}
      <span className="sr-only">
        {total} {total === 1 ? "book" : "books"} finished in {year.year}.
      </span>
    </section>
  );
}

/**
 * The homepage's present tense, in the whitespace beside the column.
 *
 * Rendered from `/` only. It could sit in the root layout and stay statically cached,
 * but that would make `/legal` and the 404 page depend on Django being reachable, and
 * a failed fetch inside a not-found page is a poor way to discover that.
 *
 * Below `xl` there is no whitespace to move into, so it stays in the flow above the
 * list. One element either way -- rendering it twice and hiding one would put the
 * same headings in the accessibility tree twice.
 */
export function NowPanel({ now }: { now: Now | null }) {
  if (!now || (!now.listening && now.year.total === 0)) return null;

  return (
    // Named on purpose. An unnamed `aside` nested inside `main` maps to `generic`
    // rather than `complementary` (HTML-AAM), so without this the landmark exists only
    // by grace of the current browser -- unreachable by landmark navigation, and an
    // e2e test that would break on a Chromium bump for reasons pointing nowhere.
    <aside
      aria-label="Now"
      className="mb-12 flex w-52 max-w-full flex-col gap-8 xl:absolute xl:top-2 xl:right-full xl:mr-10 xl:mb-0"
    >
      {now.listening && <NowListening book={now.listening} />}
      {now.year.total > 0 && <YearBar year={now.year} />}
    </aside>
  );
}
