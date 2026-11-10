# Design

## Context

See proposal.md for why. Today:

- `web/scripts/export-remote.ts` holds a Python program as a string. The
  workstation pipes it to the Pi over ssh, and it reads the stores and
  prints raw rows.
- `web/scripts/export-fixtures.ts` then maps the rows through
  `allowlist.ts` (`pick`, 4-significant-digit rounding), bins commit ages
  with `bins.ts`, and writes `web/src/data/fixtures/*.json`.
  `tests/fixtures.test.ts` scrubs the result with `scripts/scrub.ts`.
- `web/src/data/{mining,fleet,network,upgrades}.ts` import those
  fixtures and project each record through `FIELDS`. Pages read only
  these modules.
- `next.config.ts` sets `cacheComponents: true` and stamps
  `SITE_BUILT_AT` at build time. `data-age.tsx` uses that stamp for the
  server-side stale label.
- The Pi has Python 3.13 but no Node.js. Its secrets live in
  `~/.hermes/.env`. A failed user unit triggers
  `atlas-notify-failure@%n.service`, which sends the Telegram job-failure
  alert.
- Pi pass schedule: probe, chain head and repotrack hourly (around
  `:00`–`:03`); fleet reconcile every 6 h at `:20`; upgrade job every
  30 min.

## Goals / Non-Goals

**Goals:**
- Keep one implementation of composition, allowlist, rounding, binning
  and scrub, used by both the Pi publisher and the fixture refresh.
- Make no change to page components; the data layer's function
  signatures stay the same.
- Keep a site build without Supabase settings working, on fixtures.

**Non-Goals:**
- History or time series in Supabase. Only the latest board is kept.
- Client-side Supabase access or the Supabase JS client. The browser
  never talks to Supabase.
- Changing what any board contains. Field sets stay as they are.
- `subnt-publish` and the `atlas-subnt` timer.

## Decisions

### 1. One table of board documents, not one table per type

Table `public.boards`: `name text primary key` (one of `mining`, `fleet`,
`network`, `upgrades`), `generated_at timestamptz not null`,
`data jsonb not null`, `content_hash text not null`,
`published_at timestamptz not null default now()`.

The site already projects every record through `FIELDS`, so a document
per board keeps the data layer a one-line source swap. With one table
per record type, every allowlist change would need a migration, and a
board would be written as many separate upserts that could land
half-way.

### 2. Composition moves to a Python module in `sitedata/`

- The raw-row program moves out of the `export-remote.ts` string into
  `sitedata/compose.py`.
- `sitedata/atlas_sitedata.py` does the rest: `pick`, rounding, daily
  binning, scrub, and upload.
- The field allowlist and the scrub patterns move to
  `sitedata/allowlist.json` and `sitedata/scrub.json`.
- `web/scripts/allowlist.ts` and `web/scripts/scrub.ts` load those JSON
  files, so the web tests (banned fields, planted leaks, `FIELDS` parity)
  keep checking the one definition.

`export-fixtures.ts` becomes a thin wrapper. It runs
`python3 sitedata/atlas_sitedata.py compose` on the Pi over ssh and
writes the boards it prints as fixtures. It still refuses the committed
fixture directory when given `--out`.

**Alternatives considered:**
- Porting `pick` and `binDaily` to Python while keeping the TypeScript
  copies. That is two implementations that drift.
- Installing Node.js on the Pi to run the TypeScript export. That adds a
  runtime to the Pi for one job, and the composition would still live in
  a string.

A golden test in each suite checks that the same raw input gives the
same board.

`sitedata/` sits outside `web/`, so Vercel's ignore step skips the build
when only the publisher changes. The upgrade job's allowed paths do not
include it.

### 3. Uploads go through the Supabase REST API with the standard library

The publisher uses `urllib.request`:

1. It reads the current `name, content_hash, generated_at` for all
   boards in one GET.
2. It upserts only the boards whose hash or generated time differs, with
   `POST /rest/v1/boards?on_conflict=name` and
   `Prefer: resolution=merge-duplicates`.

The secret key (`SUPABASE_SECRET_KEY`) and URL (`SUPABASE_URL`) come from
`~/.hermes/.env`, the same way the Telegram module loads its credentials.
Errors pass through the existing `tg.redact`-style redaction before they
are printed.

The hash is SHA-256 over the canonical JSON of `data`. The upgrades board
takes its generated time from the run, so it uploads once an hour. That
is tiny, and it keeps the board's age honest.

### 4. Access control is row-level security with a read-only policy

- Row-level security is on for `boards`.
- One `SELECT` policy allows the `anon` role.
- There are no `INSERT`, `UPDATE` or `DELETE` policies, so the
  publishable key cannot write.
- The secret key bypasses row-level security, and it exists only on the
  Pi.

The migration lives in `sitedata/supabase/001_boards.sql` and is
applied once to the project.

### 5. The site reads in a cached server function with a fixture fallback

Each `get<Board>()` keeps its signature. Inside (`src/data/source.ts`,
with the pure parts in `source-core.ts`):

- A `'use cache'` function with
  `cacheLife({ stale: 300, revalidate: 900, expire: 1 year })` fetches
  `GET /rest/v1/boards?name=eq.<board>&select=generated_at,data` with
  the publishable key. A non-200 response or a malformed row is a
  failure. `stale` stays at 300 s: under 30 s Next leaves the cache out
  of the prerender.
- At run time a failure throws. Next then keeps serving the last good
  page (stale-while-revalidate) and retries on the next request. If the
  outer function caught the error and served the fixture, the refresh
  would succeed with fixture data and replace the last good page.
- During the build (`NEXT_PHASE=phase-production-build`), a throw inside
  a cached function fails the prerender. So the cached function returns
  a "read failed" marker instead, and the outer function serves the
  committed fixture. The marker is cached with the normal lifetime, so
  the first refresh after deploy retries the store.
- Without `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`, the fixture is
  used directly (cached with `max`), so local builds and tests need no
  network.

Verified 2026-11-10 with `next start` against a stub PostgREST and a
20-second refresh: new data appeared without a rebuild; with the store
down the page kept the last good data at HTTP 200; a build with the
store down served the fixture with the stale label, and switched to live
data on the first refresh after the store came back.

Records still pass through `onlyAll(FIELDS.*)`.

**Alternative considered:** fetch with `next: { revalidate }`. Under
`cacheComponents`, `'use cache'` is the supported caching path, and it
covers the parsing step too.

### 6. The stale label uses the read time, not the build time

- The data layer returns each board with the time it was read.
- `data-age.tsx` computes the server-side stale label from that time
  instead of `SITE_BUILT_AT`, and still recomputes in the browser.
- A cached page is at most 15 minutes behind on its label, and the
  browser corrects it.
- `SITE_BUILT_AT` and `staleAtBuild` are removed.

### 7. The publisher runs from its own timer at `:25`

- `atlas-sitedata.timer` runs `OnCalendar=*:25` with `Persistent=true`.
  That is after the hourly passes and after the 6-hourly fleet pass at
  `:20`.
- `atlas-sitedata.service` is a user `oneshot` with
  `OnFailure=atlas-notify-failure@%n.service`.
- `ExecStart=/usr/bin/python3 /home/pi/atlas/sitedata/atlas_sitedata.py publish`.

A fixed slot is simpler than hooking every pass's `ExecStartPost`, and it
publishes each pass within the hour.

## Risks / Trade-offs

- [Supabase free projects pause after a period with no activity] →
  Hourly writes are well above the documented threshold (see Open
  Questions). If the project pauses anyway, the site serves the last
  good copy with its age and the stale label.
- [A scrub false positive blocks a board] → Only that board is skipped.
  The failure alert fires, and the site keeps the previous board.
- [A schema mistake publishes a private field] → The allowlist is the
  only path a field can take. The banned-field tests run on the shared
  JSON, and the scrub runs on every board before upload.
- [Vercel's cache behaves differently from `next start` after a failed
  refresh] → Task 4.4 repeats the store-down check on a Vercel Preview
  before go-live.
- [The secret key is exposed on the Pi] → The file is 0600 in
  `~/.hermes/.env`, outside the repo. The key can only write this one
  low-value table, and it can be rotated in the Supabase dashboard.
- [Two compositions run at once (publisher and a manual fixture refresh)]
  → Both are read-only on the Atlas stores. Only the publisher writes to
  Supabase.

## Migration Plan

1. Land `sitedata/` with its tests, and switch `export-fixtures.ts` to
   it. Refresh the fixtures with it, so they match the publisher's
   output.
2. Create the Supabase project and apply `001_boards.sql`. Put the
   secret key on the Pi, then run `atlas_sitedata.py publish` once by
   hand and check the four rows.
3. Set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` in Vercel
   (Production and Preview), then deploy the data-layer change.
4. Install and enable `atlas-sitedata.timer` on the Pi.

Rollback: remove the Vercel environment variables and redeploy. The site
then serves the committed fixtures. Disable the timer on the Pi.

## Open Questions

- Answered 2026-11-10 (task 3.1): Supabase pauses a free project that
  shows low database activity over a 7-day period, after a warning email
  about a week ahead. "A few user requests to the database each day"
  is enough to prevent it, and API calls count
  (supabase.com/docs/guides/platform/free-project-pausing). The hourly
  publisher (one read and up to four upserts) and the site's reads are
  well above that. A paused project can be resumed from the dashboard
  for 90 days.
- Which Supabase region to use. Pick the one nearest the Vercel function
  region when the project is created.
