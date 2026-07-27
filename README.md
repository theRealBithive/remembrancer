# Remembrancer

A single-author public audiobook review site, sourced from a self-hosted
[Audiobookshelf](https://github.com/advplyr/audiobookshelf) instance.

Django mirrors the library nightly and surfaces a queue of books awaiting a verdict —
finished, or abandoned early enough that bailing was itself the review. You write in the Django admin. Next.js serves statically-generated public
pages with OpenGraph tags, so a link posted to Mastodon renders a proper card.

`DESIGN.md` records the 22 decisions behind the architecture and why each was made.

**Status: complete through P3** — read, Mastodon syndication, and view counting.

---

## Stack

Django 5.2 LTS · django-ninja · django-q2 · Postgres 17 · Redis 7 ·
Next.js 16 / React 19 · Caddy · uv + pnpm

## Getting started

Images are published to GHCR, so a deployment needs no build step and no checkout
beyond `compose.yaml`, the `Caddyfile` and your `.env`:

```bash
cp .env.example .env      # then fill it in -- every value is explained inline
docker compose pull
docker compose up -d      # `web` exits until the change-me secrets are replaced
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py sync_abs       # first mirror
docker compose exec web python manage.py revalidate_all  # warm the page cache
```

Then open `https://<your-domain>/<DJANGO_ADMIN_PATH>/` and write something.

`docker compose up -d --build` still builds from source instead, which is what local
development wants. To pin a release rather than track `main`, set `IMAGE_TAG` in `.env`
to a version tag or `sha-<commit>`; every CI build publishes both.

Nothing domain-specific is compiled into the frontend image — every component is a
Server Component, so `SITE_URL` and `SITE_NAME` are read at render time. One image
serves any domain, which is also why `/` and `/legal` carry a `revalidate` and why
`revalidate_all` belongs in the deploy: a page frozen at build time would print
whatever URL the builder happened to have.

### Before going public

- Set the `IMPRESSUM_*` values in `.env` (§5 DDG). Until name, street, city and email
  are all present, `/legal` says it is unconfigured rather than pretending — but the
  site will still serve, so check it. The privacy section is already accurate for what
  the code does; keep it in step if the processing changes.
- `check --deploy` runs automatically before gunicorn starts and refuses to boot on
  placeholder secrets, a missing `REVALIDATE_SECRET`, a non-HTTPS `SITE_URL`, or
  SQLite. It is skipped when `DJANGO_DEBUG` is true, so a container that starts in
  development says nothing about production.

## Posting to Mastodon

Optional and entirely manual: publishing a review does not federate it. That gap is
the point — a toot cannot be recalled, so a review stays correctable until you decide
it is finished.

1. On your instance: *Preferences → Development → New application*. Tick **only**
   `write:statuses`. The resulting token can post and do nothing else — it cannot read
   your timeline, follow anyone, or see your DMs.
2. Put it in `.env` as `MASTODON_BASE_URL` (https, no trailing slash) and
   `MASTODON_TOKEN`, then `docker compose up -d` — settings are read at process start,
   so `restart` alone will not pick them up.
3. In the admin, select reviews on the changelist → **Post to Mastodon**. The work is
   queued to `qcluster`; the *mastodon* column fills in once it lands.

The action refuses drafts (a toot linking to a 404 is worse than no toot) and reports
anything it skipped rather than pretending it posted. A review federates **at most
once, ever**: the guard is taken inside the task under `select_for_update()`, because
django-q2 retries, and `Idempotency-Key` covers the case where the post succeeds but
the response is lost.

Leave both variables unset and the action simply refuses — nothing else changes.

## View counts

Each review page counts its own reads. The number is fetched by the browser after
hydration, which is what makes it honest: a Mastodon instance building a preview card
pulls the HTML and never runs the script, so federating a post does not inflate its
readership. Those fetches also land on the static cache rather than on Django.

No cookie, no `localStorage`, no fingerprint, and therefore no consent banner. Repeat
visits are recognised by hashing the address and user agent together with a secret
random salt that lives only in Redis and rotates daily — once it rotates, yesterday's
hashes cannot be recomputed by anyone, including you. The only thing written to the
database is an integer per review per day (admin → *Review view days*).

The endpoint is world-writable, because a counter without a login or a cookie cannot
be anything else. `VIEW_BEACON_RATE` bounds the noise. Read the numbers as reach, not
as evidence.

If you change what is processed, `/legal` has to change with it — the privacy section
there describes this mechanism specifically, and it is a statement to visitors rather
than a comment.

## Asking an LLM what to read next

Admin → *Books* → **Export for an LLM**. It opens a plain-text page: select all,
paste it into a chat, and the prompt at the bottom asks for recommendations. A
450-book library comes to roughly 30 KB, about 7k tokens — small enough that nothing
has to be trimmed on the other end.

The format is one line per book with a legend at the top instead of repeated field
names, and it carries only what says something about taste: rating, your own written
verdict, listening pace, and what you abandoned. Publisher, ISBN, cover and ABS ids
are left out — they would cost context and tell a recommender nothing.

The second link omits the to-read pile. That is usually most of the library and
contributes only "already own this", so dropping it cuts the export by about two
thirds — at the price of the model occasionally suggesting something already sitting
on your shelf.

Same thing from the shell, for piping:

```bash
docker compose exec web python manage.py export_profile > profile.txt
docker compose exec web python manage.py export_profile --no-unstarted
```

The export is your whole reading history in one document. It is behind the admin
login and sent with `no-store`; treat the pasted copy with the same care.

## Everyday operations

| | |
|---|---|
| `manage.py sync_abs` | Mirror ABS now. Runs nightly via django-q2; also an admin action. |
| `manage.py revalidate_all` | Rebuild every cached page. Run after each deploy — a fresh `next build` can't reach Django, so the index ships empty. |
| Admin → Reviews → *Post to Mastodon* | Federate selected published reviews. |
| `manage.py export_profile` | Print the listening profile as LLM-readable text. Also a button on the Books changelist. |
| `docker compose logs -f qcluster` | Watch the scheduled sync. |

An expired `ABS_TOKEN` makes the sync fail loudly (non-zero exit, failed django-q2
task). That is deliberate: a silent failure would leave the finished-book queue
permanently empty while every run still looked successful.

## Tests

```bash
cd backend && uv run pytest && uv run ruff check .
cd e2e && BASE_URL=https://<your-domain> pnpm exec playwright test
```

The Playwright suite needs the full stack behind the proxy, because it checks
same-origin routing and that `/feed.xml` is served by Django.

**Run it with `DJANGO_DEBUG=false`, over TLS.** With DEBUG on, `SECURE_SSL_REDIRECT`,
HSTS, secure cookies and `CSRF_TRUSTED_ORIGINS` are all inert, so a green suite proves
nothing about how the site behaves once deployed. Locally that means mapping Caddy's
443 and pointing `SITE_URL` at it — Caddy issues an internal cert for `localhost`, and
`playwright.config.ts` sets `ignoreHTTPSErrors` for exactly that:

```yaml
# compose.override.yaml
services:
  caddy:
    ports: !override
      - "8443:443"
```
```
SITE_HOST=localhost   SITE_URL=https://localhost:8443   DJANGO_DEBUG=false
```

`tests/production-posture.spec.ts` covers what only exists in that configuration —
no redirect loop, HSTS, HTTP upgraded to HTTPS, and admin login answering 302 with the
site's own origin but 403 from a foreign one. Those tests skip themselves when
`BASE_URL` is not HTTPS, so a plain-HTTP run reports skips rather than false green. The
admin cases additionally need `ADMIN_USER` / `ADMIN_PASSWORD`.

```bash
cd e2e && BASE_URL=https://localhost:8443 HTTP_BASE_URL=http://localhost:8081 \
  ADMIN_USER=… ADMIN_PASSWORD=… pnpm exec playwright test
```

## CI

`.github/workflows/ci.yml` runs three jobs on every push and pull request:

| | |
|---|---|
| `backend` | ruff, then pytest against in-memory SQLite — no service container needed. |
| `frontend` | typecheck, build, and **fail if `/reviews/[slug]` is no longer `●`**. |
| `e2e` | builds and starts all six services in production posture, seeds demo content, runs the full Playwright suite. |

A separate `publish` workflow pushes `ghcr.io/<owner>/remembrancer-web` and
`-next` on every green `main` build and on `v*` tags. It is gated on CI succeeding, so
`latest` never points at a build whose production-posture e2e failed.

The `e2e` job also asserts that `web` *refuses* to boot on the placeholder secrets in
`.env.example`. Running CI with `DJANGO_DEBUG=true` would be the cheaper option and
would defeat the point: the class of bug this catches — SSL redirects, CSRF origins,
proxy headers — is invisible with DEBUG on.

### The one check that must not regress

```bash
cd frontend && pnpm build
```

`/reviews/[slug]` must appear as `●` (SSG), never `ƒ` (Dynamic). Reading
`headers()`, `cookies()`, or `searchParams` anywhere in that subtree silently opts
the route into dynamic rendering. The build still succeeds and the OG tags still look
correct — the only symptom is that Django starts absorbing every federated preview
fetch, which is exactly what static rendering exists here to prevent.

## Architecture notes worth knowing before you change something

**Django owns `/api/*`.** Caddy routes it there, so Next.js can never own a public
`/api` route. Its internal `/api/revalidate` hook is therefore reachable only on the
docker network; the HMAC on it is defence in depth, not the sole control.

**Next's internal fetches must send `X-Forwarded-Proto: https`.** `lib/api.ts` sets it
on every call. The hop to `web:8000` is plaintext by design — TLS terminates at Caddy —
but Django runs `SECURE_SSL_REDIRECT` in production, so without the header it answers
302 to `https://web:8000`, where gunicorn speaks plaintext. The redirect hangs until the
connect timeout and every page 500s. Those fetches also set `redirect: "error"` so a
regression fails loudly instead of hanging. None of this is visible with DEBUG on.

**Caddy serves `/static`, Django never does.** With DEBUG off Django serves nothing
under `STATIC_URL`; `collectstatic` writes into a volume shared with the proxy at boot.
Route the prefix to Django instead and every admin asset returns an HTML 404, which the
browser refuses on MIME grounds — the admin loads unstyled and its JS never runs, while
the login POST still answers 302, so anything short of opening a page in a browser
reports success.

**Same origin for everything.** That is what removes CORS configuration and
cross-site CSRF from the design entirely. Splitting the frontend onto another host
brings both back.

**`.next/cache` is a volume.** Without it, a redeploy during a federated post means a
cold cache and the full preview-fetch herd lands on Django.

**Slugs freeze at first publish.** A federated Mastodon post cannot be recalled, so a
published URL must never 404.

**Pace is the rating hint.** `Book.listening_pace` is hours of audio per calendar day;
`is_abandoned` is 90 days of silence under 15% with at least five minutes played. Both
feed the admin queue, and `is_abandoned` has a SQL twin (`Book.abandoned_q()`) because
the changelist filters on it — change one and you must change the other, which is why
a test asserts they agree.

**ABS is a source, not a dependency.** Metadata and covers are copied locally. A book
removed upstream is flagged orphaned, never deleted — its review survives.
