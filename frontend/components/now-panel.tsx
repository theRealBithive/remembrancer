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
 * Both blocks were drawn for a 208px rail, so away from that rail they need a width
 * of their own -- stretched across a phone the year bar becomes twelve fenceposts.
 *
 * `flex-col` matters as much as the width. Side by side the two sections stretch to a
 * common height, and each one puts a `flex-1` region between its heading and its rule.
 * That is what lands both rules on one line without either block being told a pixel
 * offset: a two-line book title grows both blocks together instead of knocking the
 * year bar out of alignment.
 *
 * A fixed width rather than `flex-1`, so the pair can be centred as a pair. With
 * `flex-1` each box would grow to half the row and centre inside its own half, which
 * pushes the two apart rather than bringing them together.
 */
const BLOCK = "mx-auto flex w-full max-w-64 flex-col sm:w-64 xl:w-full xl:max-w-none";

/**
 * What is on right now. Not a link: there is no review page yet, and a heading that
 * looks clickable and isn't is worse than plain text.
 */
function NowListening({ book }: { book: NonNullable<Now["listening"]> }) {
  const percent = Math.round(book.progress * 100);
  const length = runtime(book.duration_seconds);

  return (
    <section className={BLOCK}>
      <Heading>Now listening</Heading>

      {/* `pb-3` keeps the author clear of the rule. It lives inside the flex region on
          purpose: both regions have a zero flex basis, so they end up the same height
          whatever is in them, and the padding buys breathing room here without lifting
          the year bars off their own rule. */}
      <div className="mt-3 flex flex-1 gap-3 pb-3">
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
      <div className="h-px w-full bg-rule" aria-hidden="true">
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
    <section className={BLOCK}>
      <Heading>Books this year</Heading>

      {/* `flex-1` and `items-end`: the bars stand on the rule below, at whatever height
          the block has been stretched to. The min-height is what stops them collapsing
          when this is the shorter of the two blocks. */}
      <div
        className="mt-3 flex w-full flex-1 items-end gap-[3px]"
        style={{ minHeight: BAR_HEIGHT }}
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

      {/* The line the bars stand on, and the same line the progress rule opposite sits
          on. Unfilled: there is nothing to be a fraction of here. */}
      <div className="h-px w-full bg-rule" aria-hidden="true" />

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
      // `top-12` puts NOW LISTENING level with the first review's title and cover.
      // Level with the masthead was the obvious choice and the wrong one: it left the
      // progress rule a few pixels off the header's divider, and a near-miss between
      // two hairlines reads as a mistake in a way that no alignment at all does.
      //
      // The width shrinks at `xl` so the gap to the column can grow: at exactly 1280px
      // the gutter is 256px, and 208 + 40 was already using all of it. Past `2xl`
      // there is room for both.
      // Three layouts. In the rail it is a 208px column. Off the rail there is a whole
      // page width going spare, so the two blocks sit side by side rather than in a
      // 208px strip with the rest of the row empty -- which is what a phone in
      // landscape and every tablet were getting. Below `sm` there is genuinely no room
      // for two, so they stack.
      className="mb-12 flex w-full flex-col gap-8 sm:flex-row sm:justify-center sm:gap-12 xl:absolute xl:top-12 xl:right-full xl:mr-16 xl:mb-0 xl:w-44 xl:flex-col xl:justify-start xl:gap-8 2xl:mr-28 2xl:w-52"
    >
      {now.listening && <NowListening book={now.listening} />}
      {now.year.total > 0 && <YearBar year={now.year} />}
    </aside>
  );
}
