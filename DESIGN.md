# Remembrancer — Design

Public, single-author audiobook review site sourced from a self-hosted
[Audiobookshelf](https://github.com/advplyr/audiobookshelf) (ABS) instance.
Django backend, Next.js frontend, Mastodon syndication, privacy-preserving view counts.

## Verified upstream facts (ABS)

| Fact | Consequence |
|---|---|
| Auth is a long-lived JWT bearer from `POST /login` (`response.user.token`); newer builds also allow admin-created API keys | One server-side secret, rotatable |
| `mediaProgress[].isFinished` readable via `/api/me` | "Finished" can auto-drive the review queue |
| **No playback-finished webhook.** ABS notifications go via Apprise, podcast/test events only ([#1857](https://github.com/advplyr/audiobookshelf/issues/1857)) | **Poll, don't push** |
| ABS item IDs are UUIDs that change on remove/re-add | Never expose them; re-match on ASIN → title+author |

---

## Decisions

| # | Branch | Decision |
|---|---|---|
| 1 | Audience | Single-author write, anonymous public read. No accounts, registration, moderation, or comments. |
| 2 | Topology | ABS is publicly reachable over HTTPS; sync is a plain scheduled pull. |
| 3 | Sync scope | Mirror all book libraries + `/api/me` progress. Queue = `isFinished AND no review`. |
| 4 | Durability | Full local copy of metadata; covers downloaded to local media. ABS is a source, not a runtime dependency. |
| 5 | Rating | Overall 1–5 in half-steps (required) + separate narration score (optional). Prose optional. |
| 6 | Content | Markdown body, sanitized with `nh3`. `draft → published` + `published_at`. Hand-written `summary` (~300 chars). |
| 7 | Authoring | **Django admin.** Next.js is strictly read-only — zero mutating endpoints outside Django session auth. |
| 8 | Rendering | SSG/ISR with signed on-publish revalidation from Django. `generateMetadata()` emits OG tags. |
| 9 | Mastodon | Manual admin action, separate from publish. Idempotent via stored `mastodon_status_id`. `#bookstodon`. |
| 10 | View counts | Client JS beacon → Django. Dedup on daily-salted hash, cache-only. Daily buckets. |
| 11 | Site surface | Index, review detail, RSS/Atom, `/legal`. No facets until the corpus justifies them. |
| 12 | Deployment | One VPS, docker-compose, single reverse proxy, **same origin**. |
| 13 | Runtime | Postgres + Redis + **django-q2** (not Celery). |
| 14 | Security | Env-var secrets, django-axes, obscured admin path, security headers, rate-limited beacon. |
| 15 | Sync policy | Nightly + manual. Metadata is a live mirror. Orphan, never delete. |
| 16 | URLs | `/reviews/<slug>` from title+author, **frozen at publish**. |
| 17 | Phasing | P1 read → P2 reach → P3 metrics. |
| 18 | Identity | "Remembrancer". Editorial/typographic: serif body, generous measure, covers as the only colour. |
| 19 | Re-reviews | **One review per book, ever** — `OneToOneField`. Edit in place; slug and view count persist. Deliberate, not a schema artifact. |
| 20 | Legal | `/legal` route in P1 (Impressum §5 DDG + privacy notice), footer-linked sitewide. Text authored by the operator. |

---

## Two constraints the feature set creates

**Mastodon federation vs. view counts.** When a toot federates, every receiving
instance fetches the URL to build a preview card — dozens to thousands of hits with
no human behind them. Two mitigations, both already in the design:

1. Counting happens from a **client-side beacon**. Preview fetchers don't execute JS,
   so they are excluded for free.
2. Those fetches hit the **static/ISR cache**, not Django. The DB never sees the spike.

**Reach requires server-rendered OpenGraph.** A client-rendered page federates as a
bare link — no card, no cover, no title. `og:title` / `og:description` / `og:image`
on SSG pages is the mechanism the Mastodon goal depends on, not polish.

---

## Data model (Django)

```
Book
  abs_item_id        CharField, unique, indexed    # sync key; treated as mutable
  asin, isbn         CharField, nullable, indexed  # re-match keys, in priority order
  title, subtitle, authors, narrators, series, series_sequence
  duration_seconds, published_year, description
  cover              ImageField                    # local copy
  cover_source_hash  CharField                     # re-download only on change
  is_finished        BooleanField                  # from /api/me
  finished_at        DateTimeField, nullable
  is_orphaned        BooleanField                  # vanished upstream; review survives
  synced_at          DateTimeField

Review
  book               OneToOneField(Book, PROTECT)
  slug               SlugField, unique, null=True  # NULL while draft (Postgres allows
                                                   # many NULLs); set at first publish,
                                                   # frozen thereafter
  rating_overall     PositiveSmallIntegerField     # 1..10 half-steps, required
  rating_narration   PositiveSmallIntegerField, nullable
  summary            CharField(300)                # og:description + Mastodon body
  body_markdown      TextField, blank
  status             draft | published
  published_at       DateTimeField, nullable
  mastodon_status_id CharField, nullable, unique   # double-post guard
  mastodon_posted_at DateTimeField, nullable
  view_count         PositiveIntegerField          # denormalized total

ReviewViewDay
  review, date, count                              # unique_together; trend data
```

No IP, user-agent, or identifier is ever persisted. Dedup keys live only in Redis
with a short TTL.

### Re-match order on sync
`abs_item_id` → `asin` → `isbn` → normalized `title + primary author`. Only create a
new `Book` if all four miss. This is what keeps a published review attached to its
book across an ABS remove/re-add.

---

## Sync job (`manage.py sync_abs`, django-q2 `Schedule`, nightly + manual action)

1. Authenticate to ABS; token from env.
2. `GET /api/libraries` → filter to book libraries (or `ABS_LIBRARY_IDS` if set).
3. `GET /api/libraries/<id>/items` paginated → upsert `Book` via the re-match order.
4. `GET /api/me` → apply `mediaProgress[].isFinished` / `finishedAt`.
5. Download cover only when `cover_source_hash` changed.
6. Mark books absent from the response `is_orphaned = True`. **Never delete.**
7. For every changed `Book` with a *published* review, fire the Next.js revalidate hook.

Idempotent, safe to re-run, logs a per-run summary. Failure never touches published content.

**Loud failure on auth.** The job authenticates with a static env token. A `401` must
fail visibly — non-zero exit, django-q2 task marked failed, flag surfaced in the admin —
never be swallowed as "no new books". A silently expired token stops the finished-book
queue, which is the one mechanism the whole nudge loop depends on.

---

## Publish → revalidate

Django `POST`s to `/api/revalidate` on the Next.js side with an HMAC of the payload
using `REVALIDATE_SECRET`, constant-time compared. Next revalidates `/reviews/<slug>`
and `/`. The feed is **not** in that list — it is rendered dynamically by Django, so
there is no cached copy to invalidate.

A time-based `revalidate` is the safety net if the hook fails: 1 h on review pages,
60 s on the index. The index is shorter because it *is* prerendered at build time,
when Django is unreachable, so it ships empty; `manage.py revalidate_all` warms it
after each deploy and 60 s bounds the damage if that step is skipped.

## Mastodon posting

Admin action → `async_task` (django-q2). Because django-q2 retries, the guard is
checked **inside** the task under `select_for_update()`:

```
with transaction.atomic():
    review = Review.objects.select_for_update().get(pk=pk)
    if review.mastodon_status_id:
        return "already posted"
    status = client.post(...)          # Idempotency-Key header where supported
    review.mastodon_status_id = status["id"]
    review.save(update_fields=[...])
```

Body: `summary` + canonical URL + `#bookstodon`, composed against a 500-char budget
(links count as 23). Cover comes from the OG card — no media upload. Token scope
`write:statuses`, server-side only.

## View counting

`POST /api/reviews/<slug>/view` from the client after hydration.

```
key  = sha256(daily_salt + client_ip + user_agent)[:32]
if cache.add(f"v:{slug}:{key}", 1, timeout=6h):
    F()-increment Review.view_count and today's ReviewViewDay
return {"count": review.view_count}
```

The daily salt rotates and is never stored; after rotation the hash is unlinkable.
No cookie, no device storage → **no consent banner** (GDPR/ePrivacy). Endpoint is
rate-limited per hashed key. The response carries the count, so the SSG page renders
it client-side without invalidating the cache.

---

## Security posture (OWASP)

- ABS token, Mastodon token, `REVALIDATE_SECRET`, `SECRET_KEY`, DB creds via
  `django-environ`. `.env` gitignored, `.env.example` committed.
- **Nothing sensitive gets a `NEXT_PUBLIC_` prefix** — that bundle is public.
- Markdown sanitized with `nh3` on render. Single-author is not a reason to skip it.
- `django-axes` login throttling; admin on a non-obvious path. **Keyed on the real
  client**, resolved by `remembrancer.client_ip` from Caddy's `X-Real-IP` (which Caddy
  overwrites) and never from `X-Forwarded-For` (which it appends to, so a forged value
  survives). On `REMOTE_ADDR` the limiter would collapse to a single bucket holding
  every attacker on the internet, and five wrong passwords would lock the operator out
  of the only write path. P3's beacon rate limit must use the same function.
- `SECURE_SSL_REDIRECT`, HSTS, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`,
  `X_FRAME_OPTIONS=DENY`, CSP from the proxy.
- Same origin ⇒ no CORS config and no cross-site CSRF surface at all.
- Revalidate hook authenticated by HMAC, not a bearer string in a query param.
- Cover downloads: validate content-type and cap size — the sync job fetches
  remote URLs, so treat it as an SSRF-adjacent path and pin the host to `ABS_BASE_URL`.
  Off-host redirects are refused rather than followed.

**CSP carries one deliberate concession.** `script-src` includes `'unsafe-inline'`,
because Next.js emits inline bootstrap and RSC-payload scripts. The alternative —
per-request nonces — forces every page into dynamic rendering, which would defeat the
static caching Decisions 8 and 10 depend on. Without it the site does not hydrate at
all. The real XSS control is server-side: review Markdown is sanitized with `nh3`
before it leaves Django, and there is no other user-supplied content on the site.

## Deployment

```
Caddy/nginx (TLS, one domain)
  /            → Next.js (node, standalone output)
  /api, /admin → Django (gunicorn)
  /media       → cover volume
services: web(django) · qcluster(django-q2) · next · postgres · redis · proxy
```

## Phasing

- **P1 — read.** Models, `sync_abs`, admin authoring, Next.js index/detail/RSS with
  OG tags, `/legal`, revalidate hook, deploy. Solves the stated friction on its own.
  `/legal` is in P1 because it is a precondition for the site being public, not polish.
- **P2 — reach.** Mastodon action + idempotency.
- **P3 — metrics.** Beacon endpoint, dedup, daily buckets, count display.

## Deliberately out of scope

Comments, multi-user accounts, per-user ABS credentials, live ABS proxying at
request time, author/series/tag facets, full-text search, Celery.
