/**
 * Typed access to the Django read API.
 *
 * Runs server-side only, over the internal docker network. The public origin never
 * reaches Django for page data -- that is what keeps a federated Mastodon preview
 * storm on the static cache instead of the database.
 */

const DJANGO = (process.env.DJANGO_INTERNAL_URL ?? "http://web:8000").replace(/\/$/, "");

/** Matches the page-level `revalidate`; on-demand invalidation is the primary path. */
const REVALIDATE_SECONDS = 3600;

export type Book = {
  title: string;
  subtitle: string;
  authors: string;
  narrators: string;
  series: string;
  series_sequence: string;
  published_year: number | null;
  duration_seconds: number | null;
  cover_url: string | null;
  cover_thumb_url: string | null;
  days_to_finish: number | null;
  listening_pace: number | null;
};

export type ReviewSummary = {
  slug: string;
  // May be empty — a rating on its own is a complete review. `card_description` is
  // the same thing with Django's fallback already applied (body excerpt, then the
  // rating stated plainly); use it for share cards, never for the page body.
  summary: string;
  card_description: string;
  rating_overall: number;
  rating_narration: number | null;
  published_at: string | null;
  book: Book;
};

export type Review = ReviewSummary & {
  body_html: string;
  // No view count: this response is cached into the static page for up to an hour.
  // The live number comes from the beacon response, client-side.
};

/**
 * `docker build` has no route to the `web` service, so the index page cannot be
 * prerendered with real data. Only during the build itself do we degrade to an
 * empty page -- at runtime a failure must surface, not masquerade as "no reviews".
 * The deploy warms the cache afterwards (`manage.py revalidate_all`).
 */
const IS_BUILD = process.env.NEXT_PHASE === "phase-production-build";

async function get<T>(path: string): Promise<T | null> {
  const res = await fetch(`${DJANGO}${path}`, {
    // Explicit ISR caching. Notably NOT `no-store`, which would opt the whole route
    // into dynamic rendering and hand every preview fetch straight to Django.
    next: { revalidate: REVALIDATE_SECONDS },
    headers: {
      Accept: "application/json",
      // Required, not cosmetic. This hop is plaintext by design -- TLS terminates at
      // Caddy and `web:8000` is only reachable on the docker network. But Django runs
      // SECURE_SSL_REDIRECT in production, so without this header it answers 302 to
      // `https://web:8000`, where gunicorn speaks plaintext; the redirect then hangs
      // until the connect timeout and every page 500s. Invisible with DEBUG on,
      // because SECURE_SSL_REDIRECT is inert there.
      "X-Forwarded-Proto": "https",
    },
    // The internal API never legitimately redirects. Failing fast turns a
    // misconfiguration into an immediate error instead of a 10s hang per request.
    redirect: "error",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`${path} responded ${res.status}`);
  return (await res.json()) as T;
}

export async function listReviews(): Promise<ReviewSummary[]> {
  try {
    return (await get<ReviewSummary[]>("/api/reviews")) ?? [];
  } catch (error) {
    if (IS_BUILD) return [];
    throw error;
  }
}

export async function getReview(slug: string): Promise<Review | null> {
  return get<Review>(`/api/reviews/${encodeURIComponent(slug)}`);
}

/** The book in progress. One or none — never a list. */
export type NowListening = {
  title: string;
  authors: string;
  narrators: string;
  cover_thumb_url: string | null;
  duration_seconds: number | null;
  /** 0..1. The in-flight analogue of pace; no dates are published. */
  progress: number;
};

export type YearProgress = {
  year: number;
  /** 1..12, from Django's clock — the page is cached, so the browser's is not it. */
  month: number;
  total: number;
  /** Always twelve, zero-filled, January first. */
  months: number[];
};

export type Now = {
  listening: NowListening | null;
  year: YearProgress;
};

export async function getNow(): Promise<Now | null> {
  try {
    return await get<Now>("/api/now");
  } catch (error) {
    // Same escape hatch as listReviews: `docker build` cannot reach `web:8000`, and an
    // unguarded throw here fails the image build. At runtime it must still surface.
    if (IS_BUILD) return null;
    throw error;
  }
}
