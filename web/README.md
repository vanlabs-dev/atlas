# web

The subnt.dev site: a home page that explains Atlas, and four boards
(mining triage, fleet attention, network pulse, runtime upgrades). Next.js
16, Tailwind v4, Three.js for the home page field. Design record:
[DESIGN.md](DESIGN.md).

## Run

```
npm install
npm run dev        # http://localhost:3000
npm test           # fixture scrub, allowlist, export args, data-age tests
npm run test:build # build, then check every served file for dropped fields
npm run typecheck
npm run build
npm run check:browser  # state and phone checks in a real Chromium; see the script's header
```

Node 22 or newer. The Python side of the repo does not use this directory,
and the runtime upgrade job may not edit it.

## Data

Every page reads through `src/data/` (one module per board, types in
`types.ts`). Each module reads its board from Supabase at request time
(`src/data/source.ts`): the Pi publisher uploads the boards hourly, and
the site refreshes its cached copy every 15 minutes, so new data needs no
commit, push or deploy. If a refresh fails, Next keeps serving the last
good page. With no store settings, or when the store cannot be read
during the build, the pages use the committed fixtures.

| Variable | Where | Purpose |
|---|---|---|
| `SUPABASE_URL` | Vercel (Production, Preview) | Project URL, `https://<ref>.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | Vercel (Production, Preview) | Read-only public key (`sb_publishable_...`); server-side only, never sent to the browser |
| `SITEDATA_REVALIDATE_SECONDS` | Local tests only | Overrides the 15-minute refresh |

Board data is built in one place: `sitedata/` at the repository root
(see `sitedata/README.md`). It reads the latest stored pass of each input,
builds every record from the field allowlist in `sitedata/allowlist.json`,
rounds non-integer numbers to four significant digits, and bins daily
commits with the activity metric's own reader, bot patterns and window
rule, so the last 7 and 30 bins sum to the board's counts.

The committed fixtures in `src/data/fixtures/` are the fallback copy of
those boards. They do not carry the site's data, so they need refreshing
only when the fallback should be newer. Refresh them from the Pi (read-only; the Pi checkout must
have `sitedata/`):

```
node scripts/export-fixtures.ts --out /some/scratch/dir   # rehearsal
node scripts/export-fixtures.ts                           # committed fixtures
npm test
npm run test:build
```

`--out` writes a rehearsal and refuses the committed fixture directory.
The site is public, so the data is subnet-level only: no holdings,
hotkeys, wallets or addresses, and no rent, net income, payback or
hardware band (`BANNED_SOURCE` in `sitedata/allowlist.json`). `npm test`
fails on anything shaped like a token, an address, an IP or an internal
host (`sitedata/scrub.json`). `npm run test:build` builds the site and
fails if a dropped field reaches any served file. Each committed fixture
change publishes through Vercel: get the operator's yes first.

The data layer (`src/data/fields.ts`) passes each page only its typed
fields, whatever a stored board or fixture holds.

Pages show when their data was produced, and a stale label past 48
hours. The server HTML computes the label from when the page read its
data; the browser recomputes it on load.

## State machines

Every part of the site that has states names them in one place. The rules
are pure functions with tests (`tests/state.test.ts`), the components only
send events and render the state, and the state on show is published in
the DOM so a person, a test or an agent can read it.

| Machine | States | Rule | Read it in the DOM |
|---|---|---|---|
| Field stage mode | `fly`, `overlay`, `swipe`, `still`, `flat` | `src/state/flight-mode.ts` (the head script and the rule are tested against each other) | `html[data-flight]` |
| Field lifecycle | `loading`, `live`, `flat` | `src/components/home/flight.tsx` | `.figure[data-field]` |
| Field story | `hero`, `rows`, `days`, `moving` | `src/state/flight-story.ts` | `.stage[data-scene]`, `.pager [aria-current]` |
| Lead panel tab cycle | `cycling`, `held`, `offscreen`, `taken`, `still` | `src/state/lead-cycle.ts` (reducer) | `.leadp[data-cycle]` |
| Lead chart draw | `pre`, then drawn | `src/components/home/lead-panel.tsx` | `.chart[data-draw]` |
| Arrival motion | server markup, `armed`, `shown` | `src/components/home/reveal.tsx` | `[data-reveal]` |
| Count-up figure | resting on the final value, counting | `src/components/home/reveal.tsx` (`CountUp`) | the figure's text |
| Fleet tier tab | source `default`, `link`, `visitor` | `src/state/fleet-filter.ts` | `[data-filter]`, `[data-filter-source]`, `tr[data-linked]` |
| Mining scan filter | `all`, `possible`, `needs-gpu`, `other` | `src/lib/mining.ts` (`inMiningFilter`) | `[data-filter]` |
| Mining standing | `cut`, `ranked`, `unrated`, `unlisted` | `src/lib/mining.ts` (`standing`) | `tr[data-standing]` |
| Block clock | `none`, `pending`, `ticking` | `src/data/block.ts` (`blockReading`) | `[data-clock]` on the header readout |
| Data age | clock `read` or `live`; status `fresh` or `stale` | `src/data/freshness.ts` (`dataAge`) | `[data-age]`, `[data-clock]` |
| Board read plan | `fixture`; `store` failing to `fixture` (build) or `throw` (serving) | `src/data/source-core.ts` (`readPlan`) | server only |
| Pending upgrade | `waiting`, `unreleased` | `src/lib/upgrades.ts` (`pendingView`) | server only |
| Vercel build step | build, skip | `scripts/vercel-ignore.sh` (`tests/vercel-ignore.test.ts`) | build log |

To add a state: add it to the type, let the compiler show every place that
must handle it, add a test line, then style it from the attribute. Do not
add a boolean beside a machine: two booleans are four states, and one of
them is usually a bug. Next keeps a visited page alive off screen, so state
survives navigation and two pages can hold the same `id`: look a row up
inside its own table, never by document id.

## The phone

Below `md` the site is its own composition (DESIGN.md, "The phone"): the
boards are in a bottom bar, the top bar is one row, board tables are lists
of rows, filters are one sticky row, and the home field's three statements
are a strip that moves the camera. All of it is CSS on one markup, so a
link to a row works at any width.

## Deploy

Vercel, project root `web/`, production from `main`. `vercel.json` runs `scripts/vercel-ignore.sh`,
which skips the build when nothing under `web/` changed since the last
deployed commit, and builds when that commit is unknown or the commit
message holds `[build]`. Vercel runs the step on dashboard redeploys
too, so after changing only environment variables, push a commit with
`[build]` in its message (an empty commit is fine). Only code
changes deploy: data reaches the site through Supabase. Publisher
changes under `sitedata/` do not trigger a build.
