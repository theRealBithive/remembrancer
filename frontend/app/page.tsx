import Link from "next/link";

import { ListeningLine } from "@/components/listening-line";
import { NowPanel } from "@/components/now-panel";
import { Score } from "@/components/score";
import { getNow, listReviews } from "@/lib/api";
import { stars } from "@/lib/format";

/**
 * Statically generated, refreshed on demand when Django publishes.
 *
 * Shorter interval than the detail pages on purpose: this route IS prerendered at
 * build time, when Django is unreachable, so it ships empty. A minute bounds how
 * long that placeholder can survive if the post-deploy warm is ever skipped. The
 * detail pages -- the ones a Mastodon link points at -- keep the full hour.
 */
export const revalidate = 60;

export default async function IndexPage() {
  const [reviews, now] = await Promise.all([listReviews(), getNow()]);

  if (reviews.length === 0) {
    return (
      <div className="relative">
        <NowPanel now={now} />
        <p className="max-w-[var(--measure)] py-16 text-lg text-muted">
          No reviews yet. The first one lands when I finish something worth writing
          about.
        </p>
      </div>
    );
  }

  return (
    <div className="relative">
      {/* Positioned against this wrapper, so the column itself never moves. */}
      <NowPanel now={now} />

      <ol className="py-4">
        {reviews.map((review) => {
          const { book } = review;
          return (
            <li key={review.slug} className="border-b border-rule last:border-b-0">
              <Link
                href={`/reviews/${review.slug}`}
                className="group flex gap-5 py-8 outline-offset-8 sm:gap-7"
              >
                {book.cover_thumb_url && (
                  // eslint-disable-next-line @next/next/no-img-element -- Django emits
                  // both sizes at sync time, so the optimizer has nothing to add.
                  <img
                    src={book.cover_thumb_url}
                    alt=""
                    width={64}
                    height={96}
                    loading="lazy"
                    className="h-24 w-16 shrink-0 object-cover"
                  />
                )}

                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <h2 className="font-display text-xl leading-tight group-hover:underline underline-offset-4 sm:text-2xl">
                        {book.title}
                      </h2>
                      <p className="mt-1 text-sm text-muted">
                        {book.authors}
                        {book.narrators && (
                          <>
                            <span aria-hidden="true"> · </span>
                            <span className="italic">read by {book.narrators}</span>
                          </>
                        )}
                      </p>
                    </div>
                    <div className="shrink-0">
                      <Score halfSteps={review.rating_overall} />
                    </div>
                  </div>

                  {review.summary && (
                    <p className="mt-3 max-w-[52ch] text-[0.98rem] leading-relaxed text-muted">
                      {review.summary}
                    </p>
                  )}

                  <ListeningLine
                    seconds={book.duration_seconds}
                    narration={
                      review.rating_narration ? stars(review.rating_narration) : null
                    }
                  />
                </div>
              </Link>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
