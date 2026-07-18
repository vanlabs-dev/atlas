# fleet-signals — narrative radar + econ-code alerts over the subnet repo fleet

## Why

The fleet layer (subnet-repo-fleet) maintains ~104 self-healing subnet clones and
records per-`(netuid, epoch)` change ranges hourly, but nothing *interprets* those
changes — diffing/alerts were explicitly out of scope. The operator wants to use the
fleet as an investment / subnet-rotation edge: subnet teams merge code days-to-weeks
before they announce, so correlated adoption of a new dependency or model across
subnets ("a narrative forming") and changes to a subnet's reward/scoring code (its
de-facto monetary policy) are visible in the fleet before the market prices them.
This change builds that signal layer, delivered exclusively through the existing
Telegram tiering.

## What Changes

- **Term ledger**: a new fleet-DB table set recording, per qualifying *term*
  (dependency name from structured manifests, model identifier string), which netuid
  first adopted it and when — populated diff-scoped from each reconcile's new
  commits, never by rescanning the fleet. Epoch opens (new clone or re-point)
  seed the ledger from current manifest state, since change ranges only exist
  for updates.
- **Historical backfill + calibration**: a one-shot pass over existing clone history
  seeds the ledger (so day-1 produces no first-seen flood) and reconstructs the
  historical narrative timeline used to calibrate cluster thresholds before any
  alert is trusted; a companion one-shot pass seeds current model-id prevalence
  from the existing fleet-search file index so established model ids cannot fake
  "novel" clusters at launch.
- **Narrative-cluster alert class (instant tier)**: fires when k distinct subnets
  adopt the same novelty-gated term within a T-day window (defaults calibrated by
  the backfill; strawman 3 within 14 days).
- **Watchlist alert class (instant tier)**: operator-curated term list that alerts
  on first adoption by any subnet, cluster or not; shipped with a starter list,
  edited in config. Scope note: v1 matches extracted vocabulary only (dependency
  names, model ids) — a partner or product name is caught only when it surfaces
  as such; domain/URL watching is deferred with the rest of that scan surface.
- **Econ-code alert class (instant tier)**: a commit range touching a subnet's
  reward/scoring/emission code paths (path-pattern matched) alerts regardless of
  terms, dampened by a per-netuid cooldown (busy subnets digest instead of paging).
- **Adoption digest (digest tier)**: single-subnet first-adoptions of novel terms
  accrue into the existing digest cadence, never paged.
- **Alert-effectiveness tracking**: every instant-tier event snapshots the affected
  subnet's alpha price in TAO at event creation (clusters: per member subnet),
  sourced from the keyless, contract-validated TaoSwap subnets operation via the
  live-data layer (zero TaoStats quota). Configured outcome horizons (strawman
  1d/7d/30d) are filled forward and compared against a fleet-wide baseline over the
  identical window, so an `effectiveness` report can say — per alert class — whether
  alerted subnets actually outperformed the fleet. Instant alerts carry the entry
  price as one line. Measurement only: no recommendations are derived.
- **Telegram rendering**: all classes render in the established alert style
  (single-fact lines, `·` separators, safe HTML, dedup/watermark) and reuse the
  outbound notifier scan piggybacked on the hourly repo service — no new timer or
  unit.
- Scan surface is v1-narrow by design: structured manifests
  (requirements/pyproject/package/Cargo) + model-id strings. Imports, domains, and
  README vocabulary are explicitly deferred.

## Capabilities

### New Capabilities

- `fleet-signals`: extraction of qualifying terms from fleet change ranges into a
  term ledger; novelty and cluster gating; watchlist matching; econ-code path
  detection; backfill/calibration; the resulting alert/digest event contract.

### Modified Capabilities

- `telegram-integration`: adds the new alert classes (narrative-cluster, watchlist
  hit, econ-code change → instant tier; term-adoption digest → digest tier) to the
  tiered notification contract, including their rendering shape and dedup keys.

(No requirement change to `subnet-repo-fleet`: signals consume its recorded change
ranges read-only; reconciliation behavior is untouched. The `fleet-search` FTS index
is not a runtime dependency — extraction is diff-scoped; only the one-shot model-id
prevalence seed reads it. No requirement change to `live-data` either: price
snapshots consume the existing keyless TaoSwap subnets operation through the
live-data layer's own contract/fail-closed machinery, adding no endpoint, no key
use, and no TaoStats quota.)

## Impact

- **Code**: new extractor/detector module beside the existing fleet code
  (`fleet/`), owning its own ledger tables in `var/fleet/fleet.db` (same pattern as
  fleet-search's index tables: additive, reconcile store schema untouched);
  `telegram/` notifier gains the new classes; config for thresholds + watchlist.
- **Runtime**: extraction runs inline in the fleet reconcile unit; delivery
  piggybacks the existing notifier scan in the hourly repo service unit. The two
  units fire independently, so delivery lags extraction by up to one cycle —
  accepted, since every signal class moves on a days-to-weeks clock. Backfill,
  model-id seeding, and calibration are manual one-shot CLI runs on the Pi.
- **Invariants preserved**: read-only over clones, never builds/executes subnet
  code, fail-closed per slot (an unparseable manifest skips that slot's extraction,
  never blocks the pass), no secrets in alerts, Telegram failure never affects the
  reconcile.
- **Deployment**: on-device (Pi) via git pull + `init`-style migration for the new
  tables; no new systemd unit.
