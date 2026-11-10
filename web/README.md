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
```

Node 22 or newer. The Python side of the repo does not use this directory,
and the runtime upgrade job may not edit it.

## Data

Every page reads through `src/data/` (one module per board, types in
`types.ts`).

Board data is built in one place: `sitedata/` at the repository root
(see `sitedata/README.md`). It reads the latest stored pass of each input,
builds every record from the field allowlist in `sitedata/allowlist.json`,
rounds non-integer numbers to four significant digits, and bins daily
commits with the activity metric's own reader, bot patterns and window
rule, so the last 7 and 30 bins sum to the board's counts.

The committed fixtures in `src/data/fixtures/` are the fallback copy of
those boards. Refresh them from the Pi (read-only; the Pi checkout must
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
fields, whatever a fixture holds.

Pages show when their data was produced, and a stale label past 48 hours.

## Deploy

Vercel, project root `web/`, production from `main`. `vercel.json` runs `scripts/vercel-ignore.sh`,
which skips the build when nothing under `web/` changed since the last
deployed commit, and builds when that commit is unknown.
