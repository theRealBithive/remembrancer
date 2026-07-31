# Remembrancer

A single-author public audiobook review site, sourced from a self-hosted
[Audiobookshelf](https://github.com/advplyr/audiobookshelf) instance.

Django mirrors the library nightly and surfaces a queue of books awaiting a verdict —
finished, or abandoned early enough that bailing was itself the review. You write in the Django admin. Next.js serves statically-generated public
pages with OpenGraph tags, so a link posted to Mastodon renders a proper card.

`DESIGN.md` records the 25 decisions behind the architecture and why each was made.

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

Only the rating is required. Summary and body are both optional, so a book you have
nothing more to say about can be published as stars alone — the share card and the
toot fall back to the opening of the body, and then to the rating stated plainly,
rather than going out blank.

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

## Orm

A checkbox on the review form, next to the ratings. Borrowed from Walter Moers, where
the Orm is the force said to run through a writer when the work is more than well made.

It is a second axis, not a sixth star. Both ratings measure craft; this one says the
book did something to you, and the two come apart — a flawless novel can leave nothing
behind. Tick it rarely. If every 5/5 ends up marked, it is measuring nothing and should
be deleted.

Unticked means "good, and no more than good", never a complaint, and nothing is
rendered for it. Where it *is* ticked the site prints the word — never a glyph, which a
stranger cannot look up — and footnotes it at the bottom of the page. The LLM export
explains it at length, because a model reading the file cold would otherwise take
"ORM" for the database kind.

Left out of the Mastodon post deliberately: a toot carries no footnote with it.

## Synopsis

A second text box under the review body, and the only field on the site not written by
you: paste an LLM's plot summary of the book into it. Optional, and most reviews will
never have one.

It exists for the stranger arriving from a link who has not read the book — your lede
and your body both assume the plot. On the page it sits above the lede, folded shut
behind *Synopsis — skip if you already read the book (most likely LLM generated)*, in a lighter
type than the review. Closed by default because the reader it serves is the rarer one,
and labelled because it is not your voice.

Everywhere the site speaks *as* you, it is barred: the share card and its
`og:description`, the Atom feed, the Mastodon post, and the LLM export. The reason is
the same in all four — the synopsis is generated from your review, so it is your own
opinion paraphrased. Let it into the export and a recommender counts that opinion
twice and reads the repetition as a second, agreeing source. Each exclusion is held by
a test in `backend/tests/test_synopsis.py`; they guard absences, and an unasserted
absence is one tidy refactor from being helpfully filled in.

## What the homepage says about right now

Beside the review list — in the left margin above 1280px, stacked above it below —
sit two things the nightly sync keeps current: the one book you are listening to, and
twelve rules for the books you finished in each month of this year.

"Currently" is whatever Audiobookshelf played most recently, provided it is unfinished,
at least five minutes in, and was touched within the last 30 days. One book, never a
list. Nothing qualifying means the block simply isn't there.

This is the only place an **unreviewed** book appears publicly, so there is a control:
admin → *Books* → tick **hide from public** on the row. The sync never touches that box.
It hides the title, not the count — a hidden book still counts toward the year total,
because a number gives nothing away and a total that disagreed with your library would
be worse than none.

No dates are published, in keeping with the rest of the site: `/api/now` carries
`progress` and never `started_at`, `last_played_at` or `finished_at`.

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
450-book library comes to roughly 35 KB, about 9k tokens — small enough that nothing
has to be trimmed on the other end.

The format is one line per book with a legend at the top instead of repeated field
names, and it carries only what says something about taste: rating, the Orm mark,
listening pace, what you abandoned, and your reviews in full — summary and body both,
quoted with `> `. The summary alone is written for a Mastodon card; the reasons are in
the body, and the reasons are the point. Publisher, ISBN, cover and ABS ids are left
out — they would cost context and tell a recommender nothing.

Four things in there came out of actually running the experiment: pasting the whole
file into a model, asking for recommendations, and reading what it could not see.

**The narrator.** This is an audiobook library, so a reader is a reason to pick a book
up and a reason to put one down, and the file said nothing about it. Books you have
heard now name theirs. The to-read pile does not — that section is most of the export
and exists only to say "already owned", and the reader there is one you have never
heard, so the name is pure cost. Cutting it there is what pays for it everywhere else.

**Comfort reading.** Tick *comfort read* on the Books changelist, or select a shelf and
use the bulk action — this arrives as a series, thirty-odd tie-in novels at a time, and
a flag applied one row at a time stays permanently half-applied. Marked books are still
in the export, still in whatever section their state puts them, but flagged `comfort`
and explicitly fenced off in the legend: a recommender may serve them if you ask, and
must never average them into the main taste. Without this the file simultaneously
claims you devour military tie-ins and revere Le Guin, both true, and produces a
recommendation matching neither.

**Dates.** Year and month, never the day: `finished 2026-03`, or `last touched 2026-07`
on something in progress — which also exposes the books you gave up on without
admitting it. The public site deliberately withholds the calendar (Decision 21); this
file is your own history handed to a model on purpose, and without a rough date a
recommender cannot tell the taste you had at twenty from the one you have now.

**Why you stopped.** *Cryptonomicon* at 3% and something you actively disliked at 3%
are the same line in the file and opposite verdicts. The *abandoned note* field on the
changelist prints as a `why:` line, and the legend says how to read it: "wrong moment"
means keep suggesting this kind of thing, "not for me" means stop.

Those three fields — *hide from public*, *comfort read*, *abandoned note* — are the
only values on `Book` that are yours rather than Audiobookshelf's. They are listed in
`catalog.models.AUTHORED_FIELDS` and kept out of `sync.MIRRORED_FIELDS`, with a test
holding the two apart, because the failure mode is silent: add one to the mirror and
the nightly sync erases it with no error and nothing to notice.

The second link omits the to-read pile. That is usually most of the library and
contributes only "already own this", so dropping it cuts the export by about two
thirds — at the price of the model occasionally suggesting something already sitting
on your shelf.

Same thing from the shell, for piping:

```bash
docker compose exec web python manage.py export_profile > profile.txt
docker compose exec web python manage.py export_profile --no-unstarted
```

One field never appears here: the **synopsis**. It is written by a model from your own
review, so exporting it would hand a recommender your opinion a second time, in a
different voice, where it reads as an independent second observation. See
[Synopsis](#synopsis).

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
