# web

The subnt.dev site: a home page that explains Atlas, and four boards
(mining triage, fleet attention, network pulse, runtime upgrades). Next.js
16, Tailwind v4, Three.js for the home page field. Design record:
[DESIGN.md](DESIGN.md).

## Run

```
npm install
npm run dev        # http://localhost:3000
npm test           # fixture scrub, allowlist, export, data-age tests
npm run test:build # build, then check every served file for dropped fields
npm run typecheck
npm run build
```

Node 22 or newer. The Python side of the repo does not use this directory,
and the runtime upgrade job may not edit it.

## Data

Every page reads through `src/data/` (one module per board, types in
`types.ts`). Today the modules return committed fixtures from
`src/data/fixtures/`. A live source replaces the module bodies and keeps
their signatures.

Fixtures come from a read-only export of the Pi's stores:

```
node scripts/export-fixtures.ts --out /some/scratch/dir   # rehearsal
node scripts/export-fixtures.ts                           # committed fixtures
npm test
npm run test:build
```

The export reads the latest stored pass of each input: the mining pass,
the feasibility scans current for it, the fleet board and the network
rows. It builds every record from the field allowlist in
`scripts/allowlist.ts` and rounds non-integer numbers to four significant
digits. `--out` writes a rehearsal and refuses the committed fixture
directory. Daily commit bins use the activity metric's own commit reader
and bot patterns, and its window rule (`scripts/bins.ts`), so the last 7
and 30 bins sum to the board's counts. The site is public, so the data is
subnet-level only: no holdings, hotkeys, wallets or addresses, and no
rent, net income, payback or hardware band (`BANNED_SOURCE`). `npm test`
fails on anything shaped like a token, an address, an IP or an internal
host. `npm run test:build` builds the site and fails if a dropped field
reaches any served file. Each committed fixture change publishes through
Vercel: get the operator's yes first.

The data layer (`src/data/fields.ts`) passes each page only its typed
fields, whatever a fixture holds.

Pages show when their data was produced, and a stale label past 48 hours.

## Deploy

Vercel, project root `web/`, production from `main`. `vercel.json` runs `scripts/vercel-ignore.sh`,
which skips the build when nothing under `web/` changed since the last
deployed commit, and builds when that commit is unknown.
