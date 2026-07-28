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
| 3 | Sync scope | Mirror all book libraries + `/api/me` progress. Queue = finished **or abandoned**, and no review. |
| 4 | Durability | Full local copy of metadata; covers downloaded to local media. ABS is a source, not a runtime dependency. |
| 5 | Rating | Overall 1–5 in half-steps (required) + separate narration score (optional). Prose optional. |
| 6 | Content | Markdown body, sanitized with `nh3`. `draft → published` + `published_at`. Optional hand-written `summary` (~300 chars); a rating alone is a complete review. |
| 7 | Authoring | **Django admin.** Next.js is strictly read-only — zero mutating endpoints outside Django session auth. |
| 8 | Rendering | SSG/ISR with signed on-publish revalidation from Django. `generateMetadata()` emits OG tags. |
| 9 | Mastodon | Manual admin action, separate from publish. Idempotent via stored `mastodon_status_id`. `#bookstodon`. |
| 10 | View counts | Client JS beacon → Django. Dedup on daily-salted hash, cache-only. Daily buckets. |
| 11 | Site surface | Index, review detail, RSS/Atom, `/legal`. No facets until the corpus justifies them. Index also carries the present tense — see 23. |
| 12 | Deployment | One VPS, docker-compose, single reverse proxy, **same origin**. |
| 13 | Runtime | Postgres + Redis + **django-q2** (not Celery). |
| 14 | Security | Env-var secrets, django-axes, obscured admin path, security headers, rate-limited beacon. |
| 15 | Sync policy | Nightly + manual. Metadata is a live mirror. Orphan, never delete. |
| 16 | URLs | `/reviews/<slug>` from title+author, **frozen at publish**. |
| 17 | Phasing | P1 read → P2 reach → P3 metrics. |
| 18 | Identity | "Remembrancer". Editorial/typographic: serif body, generous measure, covers as the only colour. |
| 19 | Re-reviews | **One review per book, ever** — `OneToOneField`. Edit in place; slug and view count persist. Deliberate, not a schema artifact. |
| 20 | Legal | `/legal` route in P1 (Impressum §5 DDG + privacy notice), footer-linked sitewide. Text authored by the operator. |
| 21 | Listening record | Capture `startedAt`/`lastUpdate`/`progress`. Pace (h of audio per calendar day) is the rating hint; abandonment is a reviewable verdict. Pace is public, dates are not — softened by 23, which publishes a month. |
| 22 | Distribution | Images published to GHCR by CI. Nothing domain-specific is baked in, so one image serves any deployment. |
| 23 | Present tense | Homepage shows the one book in progress and a twelve-month bar of books finished this year. Publishes an **unreviewed** book and a monthly calendar; `Book.hide_from_public` is the control. |

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
  started_at         DateTimeField, nullable       # first play
  finished_at        DateTimeField, nullable
  last_played_at     DateTimeField, nullable       # silence since => abandoned
  progress           FloatField                    # 0..1
  seconds_listened   PositiveIntegerField, nullable
  is_orphaned        BooleanField                  # vanished upstream; review survives
  hide_from_public   BooleanField                  # keeps a title out of "now
                                                   # listening"; the one authored field
                                                   # here, so absent from MIRRORED_FIELDS
  synced_at          DateTimeField

Review
  book               OneToOneField(Book, PROTECT)
  slug               SlugField, unique, null=True  # NULL while draft (Postgres allows
                                                   # many NULLs); set at first publish,
                                                   # frozen thereafter
  rating_overall     PositiveSmallIntegerField     # 1..10 half-steps, required
  rating_narration   PositiveSmallIntegerField, nullable
  summary            CharField(300, blank)         # og:description + Mastodon body;
                                                   # optional -- card_description falls
                                                   # back to the body, then the rating
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

## The listening record

How long a book took relative to its length is the strongest signal available for how
much it was enjoyed, and it costs nothing: ABS already tracks it.

```
days_to_finish  = finished_at - started_at
listening_pace  = (duration_seconds / 3600) / days_to_finish     # h of audio per day
is_abandoned    = not finished AND >= 90 days silent
                  AND progress < 15% AND >= 5 minutes listened
```

Pace normalises length away, which is the entire point: four days on a 14-hour book is
a different act from four days on a three-hour one. Measured against a real 456-book
library the spread is wide and legible — 4.1 h/day over 1.6 days at one end, 0.05 h/day
over 369 days at the other.

The five-minute floor is what separates a verdict from a mis-tap. Without it, 7 of 22
candidates were books opened once and closed, which say nothing worth writing down.

`is_abandoned` has a SQL twin, `Book.abandoned_q()`, because the changelist has to
filter on it. They are defined next to each other and tested against each other: two
definitions that drifted would show one set of books in the queue and a different flag
on each row.

**Pace is published; dates are not.** "Over 3 days, 5.4 h/day" is a judgement and reads
as editorial. Start and finish dates would publish a listening calendar, which is
nobody's business.

### The present tense on the homepage (Decision 23)

Between reviews the site showed no sign of life, which is odd for something calling
itself a listening record. Two blocks in the whitespace beside the index fix that:
the book currently in progress, and twelve rules — one per month — for what was
finished this year.

Both cross a line the rest of the site holds. Everywhere else a book becomes public
only when a review is written *and* published; now-listening puts an unreviewed book
up the night it is started. And a month is a calendar, which the paragraph above
refuses. The concessions are bounded deliberately:

- `progress` is published, timestamps are not. It is the in-flight analogue of pace —
  a judgement, not a diary. `/api/now` carries no `started_at`, `last_played_at` or
  `finished_at`, and a test asserts the exact key set.
- A month is coarse enough to read as a rhythm. A finishing *date* would not be.
- `Book.hide_from_public` keeps a title off the page, ticked from the changelist row.
  It hides the title, not the arithmetic: a hidden book still counts toward the year
  total, because a number reveals nothing and a count that quietly disagreed with the
  library would be worse than no count.
- "Currently" means ABS's `lastUpdate` within 30 days, above the same five-minute floor
  `is_abandoned` uses. Well short of the 90 days that mark a book abandoned — a book
  silent since last month is not what you are listening to.

`hide_from_public` is the only authored field in `catalog`, so it is deliberately
absent from `sync.MIRRORED_FIELDS`; the nightly mirror would otherwise overwrite it.
It survives an ABS remove/re-add for the same reason a review does — `Book.match()`
re-adopts the existing row.

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

Body: `title — authors · N/5`, then `card_description`, then the canonical URL and the
hashtags, composed against a 500-char budget where links count as 23 regardless of
length. When it does not fit, the description is trimmed first and the header second: the
link is the entire reason for posting and the hashtags are what give it reach, so
neither is ever sacrificed. Cover comes from the OG card — no media upload.

Token scope `write:statuses`, server-side only, and the base URL is required to be
`https://` — the token rides on that request, so a plaintext instance would hand it
to the network. Unset credentials are not an error state: the action simply refuses,
which is what makes syndication genuinely optional.

The action also refuses a draft. A toot linking to a page that does not exist yet is
worse than no toot, and unlike the page, the toot cannot be fixed later.

## View counting

`POST /api/reviews/<slug>/view` from the client after hydration.

```
key  = sha256(daily_salt + client_ip + user_agent)[:32]
if cache.add(f"v:{slug}:{key}", 1, timeout=6h):
    F()-increment Review.view_count and today's ReviewViewDay
return {"count": review.view_count}
```

The daily salt is `secrets.token_hex(32)`, held only in the cache under a
`localdate()`-keyed name with a 26 h TTL. It rotates daily and is never stored; after
rotation the hash cannot be recomputed, by us or by anyone. No cookie, no device
storage → **no consent banner** (GDPR/ePrivacy). Endpoint is rate-limited per hashed
key, using the same hash and the same `client_ip()` as the axes lockout.

The response carries the count, so the SSG page renders it client-side without
invalidating the cache. `ReviewOut` deliberately omits `view_count`: baked into an ISR
page it would be an hour stale, and rendering it would invite exactly that.

Both increments run as queryset `.update(count=F(...) + 1)`. Going through
`Review.save()` would widen `update_fields` with the bookkeeping set and fire the
revalidate signal — every read would then invalidate the page it was counting. A
queryset update emits no `post_save` at all.

The counter is world-writable and trivially inflatable by anyone willing to rotate a
user agent. That is inherent to a beacon with no cookie and no login; the throttle
bounds the noise and is not an integrity control.

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
  /static      → collectstatic volume (Django serves none of this with DEBUG off;
                 proxying the prefix to it yields HTML 404s and a broken admin)
services: web(django) · qcluster(django-q2) · next · postgres · redis · proxy
```

Images are built and pushed to GHCR by CI, only after the production-posture e2e job
passes. Nothing domain-specific is baked into them: every component in the frontend is
a Server Component, so `SITE_URL` and `SITE_NAME` are read at render time rather than
compiled into a bundle. That is what makes one published image usable on any domain --
and why `/legal` and `/` carry a `revalidate`, since a page frozen at build time would
print whatever URL the builder happened to have.

## Phasing

- **P1 — read.** *Done.* Models, `sync_abs`, admin authoring, Next.js index/detail/RSS with
  OG tags, `/legal`, revalidate hook, deploy. Solves the stated friction on its own.
  `/legal` is in P1 because it is a precondition for the site being public, not polish.
- **P2 — reach.** Mastodon action + idempotency. *Done.*
- **P3 — metrics.** Beacon endpoint, dedup, daily buckets, count display. *Done.*

## Listening profile export

Admin-only plain text, one line per book, a legend instead of repeated field names.
Carries rating, the review in full (summary *and* body, quoted with `> `), pace and
abandonment; omits publisher, ISBN, the upstream description, covers and ABS ids.
~30 KB for 450 books and three reviews; each further review adds its own length.

The judgement here is about what constitutes signal, not about the format. Pace and
abandonment are in because they are verdicts given without meaning to; the blurb and
the publisher are out because a recommender learns nothing from them and they would
triple the size. A reviewed book stays in the export after it is orphaned upstream —
the verdict was authored, and it still describes the taste.

Not an API and not public: it is one person's entire reading history behind
`admin_view()` and `no-store`.

## Deliberately out of scope

Comments, multi-user accounts, per-user ABS credentials, live ABS proxying at
request time, author/series/tag facets, full-text search, Celery.
