# sitedata

Builds the public subnt.dev boards (mining, fleet, network, upgrades)
from the Atlas stores. It is the only place where site data is composed.
The Pi publisher and the committed web fixtures both come from it
(change: `supabase-data-layer`).

## Commands

Run from the repository root:

```
python3 sitedata/atlas_sitedata.py compose   # print the four boards as JSON
python3 sitedata/atlas_sitedata.py publish   # upload changed boards to Supabase
```

`compose` is read-only. It opens every SQLite store with `mode=ro`, reads
git logs only, and writes nothing.

`publish` composes the boards, scrubs each one, and upserts every clean
board whose data or generated time differs from the stored copy into the
Supabase `boards` table (`supabase/001_boards.sql`). It reads
`SUPABASE_URL` and `SUPABASE_SECRET_KEY` from `~/.hermes/.env`, or else the
process environment, and never prints the key. It exits 1 when a
credential is missing (before composing), when the store cannot be
reached or rejects a write, or when any board fails the scrub. Clean
boards still upload in that last case. It never deletes or blanks a
stored board.

On the Pi, `systemd/atlas-sitedata.timer` runs `publish` hourly at `:25`,
after the hourly passes and the 6-hourly fleet pass at `:20`. A failed
run triggers `atlas-notify-failure@`, the Telegram job-failure alert.
Install steps are in the unit file.

## Files

| File | Holds |
|---|---|
| `compose.py` | Raw rows from the stores: the latest stored pass of each input, with no age limit |
| `atlas_sitedata.py` | `pick` (allowlist), 4-significant-digit rounding, daily commit bins, board assembly, scrub |
| `allowlist.json` | Field allowlist (site field to source field), banned source-field pattern, day series, public signal classes |
| `scrub.json` | Leak rules: tokens, IP addresses, hosts, private addresses, dropped or rent-bounding fields, em dashes |
| `supabase/001_boards.sql` | The `boards` table: public `SELECT`, no public write (row-level security) |
| `systemd/` | `atlas-sitedata.service` and `.timer` for the Pi |
| `tests/golden/` | A synthetic raw input and the boards the TypeScript export built from it |

## Rules

- A field reaches the site only if `allowlist.json` names it. A field the
  stores add later is dropped until someone lists it.
- Never list owner data: holdings, positions, hotkeys, wallets, rotation
  decisions, or any address.
- The web tests read the same two JSON files: `web/scripts/allowlist.ts`
  (banned fields, `FIELDS` parity) and `web/scripts/scrub.ts`. Change a
  rule in the JSON, never in a copy.
- A board with any scrub finding is not published.

## Tests

```
python3 -m unittest discover -s sitedata/tests
```

No test reaches the network or the Pi stores: publish tests use a fake
transport.
