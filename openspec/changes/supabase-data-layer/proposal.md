# Proposal

## Why

subnt.dev only shows new data when someone re-exports the Pi stores and
pushes the committed fixtures, so on 2026-11-10 every page still showed
5 November data while the Pi held data from that morning. A push per data
change also means a full Vercel build per update, which the free plan
cannot sustain at Atlas's hourly cadence.

## What Changes

- Add a site-data publisher on the Pi. After the Atlas passes it builds
  the four boards (mining, fleet, network, upgrades) from the live stores,
  applies the field allowlist, rounding and scrub, and upserts each board
  to Supabase. It needs no Node.js and makes outbound HTTPS calls only.
- Add a Supabase project that holds only published board documents.
  Public reads are allowed; writes need the publisher's secret key.
- Change the site data layer to read the boards from Supabase at request
  time, cached and refreshed every 15 minutes. Data changes no longer
  need a commit, a push, or a deploy.
- Keep the committed fixtures only as a fallback for when Supabase is
  unreachable and no cached copy exists. The page shows the age of
  whichever copy it serves.
- Compute the stale label when the page is rendered, not when it is
  built.
- Move the field allowlist, rounding and daily binning to one shared
  definition that both the Pi publisher and the site tests read.
- **BREAKING** for the operator workflow: `node scripts/export-fixtures.ts`
  is no longer the way the site gets data. It stays only to refresh the
  fallback fixtures.

## Capabilities

### New Capabilities
- `site-data-publish`: the Pi job that composes the public boards from
  the Atlas stores and publishes them to the hosted store, including its
  privacy gate, schedule, failure handling and credentials.

### Modified Capabilities
- `subnt-dev-site`: the data layer reads the hosted store at request
  time with a fixture fallback; the stale label is computed at render
  time; the allowlist and scrub requirements now apply to the publisher
  output as well as to the committed fixtures.

## Impact

- New: a publisher module and its tests in a new `sitedata/` directory,
  a systemd user timer and service on the Pi, and a Supabase project
  with one table and its access policy.
- Changed: `web/src/data/*.ts`, `web/src/components/data-age.tsx`,
  `web/src/data/freshness.ts`, `web/scripts/allowlist.ts`,
  `web/scripts/export-remote.ts` and `web/scripts/export-fixtures.ts`,
  plus their tests and `web/README.md`.
- Secrets: a Supabase secret key on the Pi (in `~/.hermes/.env`, like
  the other Pi secrets); the Supabase URL and publishable key as Vercel
  environment variables.
- Dependencies: no new Python packages (standard library HTTP); the
  site gains no new npm dependency (plain `fetch` to the Supabase REST
  API).
- `subnt-publish` (the older subnt checkout publisher, timer masked
  since 2026-09-28) is unchanged by this change.
