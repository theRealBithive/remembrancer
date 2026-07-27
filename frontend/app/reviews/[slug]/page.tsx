import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ListeningLine } from "@/components/listening-line";
import { Score } from "@/components/score";
import { getReview } from "@/lib/api";
import { listeningDate, stars } from "@/lib/format";

/**
 * Statically generated with on-demand invalidation.
 *
 * Nothing in this subtree may read headers(), cookies(), or searchParams: any one
 * of them silently opts the route into dynamic rendering. The build still succeeds
 * and the OG tags still look right, so the only symptom would be Django quietly
 * absorbing every federated preview fetch. `pnpm build` must show this route as
 * static (marked with a filled circle), never dynamic.
 */
export const revalidate = 3600;
export const dynamicParams = true;

export async function generateStaticParams() {
  // Deliberately empty: enumerating slugs here would require Postgres and Django to
  // be reachable during `docker build`. Pages are generated on first request and
  // cached from then on.
  return [];
}

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const review = await getReview(slug);
  if (!review) return { title: "Not found" };

  const { book } = review;
  const title = `${book.title} — ${book.authors}`;
  const path = `/reviews/${review.slug}`;

  // This block is the mechanism the Mastodon reach depends on: an instance building
  // a preview card reads exactly these tags out of the server-rendered HTML.
  return {
    title,
    description: review.summary,
    alternates: { canonical: path },
    openGraph: {
      type: "article",
      title,
      description: review.summary,
      url: path,
      publishedTime: review.published_at ?? undefined,
      images: book.cover_url ? [{ url: book.cover_url, alt: `Cover of ${book.title}` }] : [],
    },
    twitter: {
      card: book.cover_url ? "summary_large_image" : "summary",
      title,
      description: review.summary,
      images: book.cover_url ? [book.cover_url] : [],
    },
  };
}

export default async function ReviewPage({ params }: Props) {
  const { slug } = await params;
  const review = await getReview(slug);
  if (!review) notFound();

  const { book } = review;
  const published = listeningDate(review.published_at);

  return (
    <article className="py-8">
      <header className="flex flex-col gap-7 sm:flex-row sm:gap-9">
        {book.cover_url && (
          // eslint-disable-next-line @next/next/no-img-element -- see next.config.ts
          <img
            src={book.cover_url}
            alt={`Cover of ${book.title}`}
            width={160}
            height={240}
            className="h-60 w-40 shrink-0 object-cover"
          />
        )}

        <div className="min-w-0 flex-1">
          <h1 className="font-display text-3xl leading-[1.1] sm:text-4xl">{book.title}</h1>
          {book.subtitle && (
            <p className="mt-2 font-display text-lg text-muted">{book.subtitle}</p>
          )}

          <p className="mt-3 text-[0.98rem]">
            {book.authors}
            {book.narrators && (
              <>
                <span aria-hidden="true"> · </span>
                <span className="italic text-muted">read by {book.narrators}</span>
              </>
            )}
          </p>

          <dl className="mt-5 flex flex-wrap gap-x-7 gap-y-1 font-mono text-[0.7rem] uppercase tracking-[0.12em] text-muted">
            {book.series && (
              <div>
                <dt className="sr-only">Series</dt>
                <dd>
                  {book.series}
                  {book.series_sequence && ` ${book.series_sequence}`}
                </dd>
              </div>
            )}
            {book.published_year && (
              <div>
                <dt className="sr-only">Published</dt>
                <dd>{book.published_year}</dd>
              </div>
            )}
            {published && (
              <div>
                <dt className="sr-only">Reviewed</dt>
                <dd>Reviewed {published}</dd>
              </div>
            )}
          </dl>

          <div className="mt-6 flex items-end gap-8">
            <div>
              <Score halfSteps={review.rating_overall} size="lg" />
              <p className="mt-2 font-mono text-[0.65rem] uppercase tracking-[0.16em] text-muted">
                Overall
              </p>
            </div>
            {review.rating_narration && (
              <div>
                <Score halfSteps={review.rating_narration} />
                <p className="mt-2 font-mono text-[0.65rem] uppercase tracking-[0.16em] text-muted">
                  Narration
                </p>
              </div>
            )}
          </div>
        </div>
      </header>

      <ListeningLine seconds={book.duration_seconds} />

      <hr className="mt-10 border-0 border-t border-rule" />

      <p className="mt-10 max-w-[var(--measure)] font-display text-xl leading-snug sm:text-2xl">
        {review.summary}
      </p>

      {review.body_html && (
        <div
          className="prose mt-8"
          // Sanitized server-side by nh3 before it ever leaves Django (reviews/markdown.py).
          dangerouslySetInnerHTML={{ __html: review.body_html }}
        />
      )}
    </article>
  );
}
