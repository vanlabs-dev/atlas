# web

The subnt.dev site: a home page that explains Atlas, and four boards
(mining triage, fleet attention, network pulse, runtime upgrades). Next.js
16, Tailwind v4, Motion. Design record: [DESIGN.md](DESIGN.md).

## Run

```
npm install
npm run dev        # http://localhost:3000
npm test           # fixture scrub, allowlist, data-age tests
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

Fixtures come from a one-off, read-only export of the Pi's stores:

```
node scripts/export-fixtures.ts
npm test
```

The export builds every record from the field allowlist in
`scripts/allowlist.ts`, rounds numbers to four significant digits, and
cuts time series off seven days before the run. The site is public, so the
data is subnet-level only: no holdings, hotkeys, wallets or addresses.
`npm test` fails on anything shaped like a token, an address, an IP or an
internal host. Run it before committing new fixtures.

Pages show when their data was produced, and a stale label past 48 hours.

## Deploy

Vercel, project root `web/`. `vercel.json` runs `scripts/vercel-ignore.sh`,
which skips the build when nothing under `web/` changed since the last
deployed commit, and builds when that commit is unknown.
