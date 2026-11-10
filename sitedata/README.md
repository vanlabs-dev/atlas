# sitedata

Builds the public subnt.dev boards (mining, fleet, network, upgrades)
from the Atlas stores. It is the only place where site data is composed.
The Pi publisher and the committed web fixtures both come from it
(change: `supabase-data-layer`).

## Commands

Run from the repository root:

```
python3 sitedata/atlas_sitedata.py compose   # print the four boards as JSON
```

`compose` is read-only. It opens every SQLite store with `mode=ro`, reads
git logs only, and writes nothing.

## Files

| File | Holds |
|---|---|
| `compose.py` | Raw rows from the stores: the latest stored pass of each input, with no age limit |
| `atlas_sitedata.py` | `pick` (allowlist), 4-significant-digit rounding, daily commit bins, board assembly, scrub |
| `allowlist.json` | Field allowlist (site field to source field), banned source-field pattern, day series, public signal classes |
| `scrub.json` | Leak rules: tokens, IP addresses, hosts, private addresses, dropped or rent-bounding fields, em dashes |
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

No test reaches the network or the Pi stores.
