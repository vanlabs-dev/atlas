# Proposal

## Why

subnt.dev has no site. Atlas builds and consolidates subnet data that only
the owner sees, through Telegram. A public site gives visitors a clear
picture of what Atlas is and gives the owner a glance view of the data.
Design is the priority, so the site comes first on fixture data and real
data follows later.

## What Changes

- Add a Next.js 16 app in `web/` (Tailwind v4, shadcn/ui, TypeScript, Motion).
- Add five pages: home, mining triage, fleet attention with rotation
  signals, network pulse, runtime-upgrade timeline.
- Add a typed data layer. All pages read through it. Fixtures back it now.
- Seed the fixtures from a one-off export of the live Atlas stores, then
  scrub the export before it is committed.
- Dark mode first, motion that honours `prefers-reduced-motion`.
- Pick the visual direction with `design-taste-frontend` (`draw.mjs`,
  `inspect.mjs`) and `ui-ux-pro-max`.
- Add a Vercel ignored-build step so upgrade pushes to `main` do not redeploy.
- Add a test that the runtime upgrade scope gate rejects `web/` paths.
- Fix the README line that calls subnt.dev retired, when the site ships.

Out of scope: the publisher, Supabase schema, leak scan, publish gate,
retiring subnt-trader, logins, wallet tracking, trading advice, public chat,
paid Desearch.

## Capabilities

### New Capabilities
- `subnt-dev-site`: the public site and owner glance view, its pages, its
  data-layer boundary, its fixture hygiene, and its isolation from the
  runtime upgrade job.

### Modified Capabilities

None.

## Impact

- New directory `web/` (own `package.json`, Node 22+).
- `upgrade/tests`: one new scope test. No change to `upgrade/allowed_paths.py`
  expected, since `web/` is not in `ALLOWED`.
- `README.md` and `tools/readme_sync.py` output: new component row for `web/`.
- New dev dependencies: Next.js 16, Tailwind v4, shadcn/ui, Motion.
- Vercel project config for subnt.dev (owner action).

Approved: 2026-10-30
