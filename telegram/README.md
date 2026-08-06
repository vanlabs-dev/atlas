# telegram — Phase 5 controlled Telegram channel

Two halves with different owners:

- **Inbound conversation** — the native NousResearch Hermes Telegram
  gateway, configured by the operator (`hermes gateway setup`). Atlas writes
  no gateway code; see [docs/operator-setup.md](docs/operator-setup.md).
- **Outbound operational notifier** — [`atlas_telegram.py`](atlas_telegram.py),
  the only code in this module. It turns events already produced by earlier
  phases into de-duplicated, secret-scrubbed alerts and records every
  delivery.

Governing spec: PRD §12.11 (ATLAS-TG-001…006) and the accepted
`telegram-integration` capability.

## Outbound notifier

Fail-closed, stdlib-only, read-only toward the device except its own 0600
`var/telegram/` store.

**Event classes** (each reads an existing store read-only, past a persisted
per-source watermark, and never mutates or invents). Class order is delivery
priority — a live chain upgrade surfaces before repo alerts in the same scan:

| Class | Source | Trigger |
|---|---|---|
| `chain-runtime-upgrade` | `var/livedata/livedata.db` (`spec_upgrades`) | the **live** Finney runtime `spec_version` changed (the network changed) |
| `chain-parameter-change` | `var/livedata/livedata.db` (`chain_param_events`) | a root-settable economic knob changed value (change: network-drift-443): the three emission-gate bar parameters plus `RootWeightSettingEnabled`, the Root Reborn curation switch. Instant tier, **no cooldown and no digest** — such a knob cannot burst, and suppressing a second flip would be the wrong failure. A bar-parameter transition also states that the bar was re-priced for every subnet and that per-subnet crossing pages were withheld for that pass |
| `gate-crossing` | `var/livedata/livedata.db` (`gate_events`) | a subnet's demand share crossed the emission-gate bar in either direction (change: gate-crossing-signal) — an economic cliff event; instant tier with a per-netuid cooldown. Since network-drift-443 the body also names the active bar mode (rank-pinned or q-mass) and the bar's own movement, attributing the crossing to the bar when the bar alone accounts for it |
| `fleet-signal` | `var/fleet/fleet.db` (`signal_events`, read **strictly read-only**) | fleet-signals queue (change: fleet-signals): `narrative-cluster` / `watchlist` / `econ-code` page immediately; `signal-digest` rows are held durably in `pending_signal`, ride the next instant fleet alert, or flush via `digest_backstop_hours` — never paged, never dropped |
| `repository-update` | `var/repotrack/repotrack.db` (`change_ranges`) | a **significant** tracked commit range (Phase 3 timer); churn is digested, not paged |
| `schema-drift` | `var/livedata/livedata.db` (`integration_health`) | a live provider response stopped validating (Phase 4) |
| `knowledge-ingestion` | `var/knowledge/knowledge.db` (`intake_runs`) | a new ingest run staged units for review (Phase 2) |

**Fleet signal alerts** carry the term/subnet facts as single-fact `·`
lines (cluster: members, first mover with date and `code` SHA, adoption
window, fleet prevalence; watchlist: term, source file, commit; econ-code:
range SHAs, commit count, matched files) plus one entry-price line (alpha
in TAO) when the fleet's price snapshot is already recorded — a pending
snapshot omits the line and never delays delivery. Terms and paths
originate in untrusted subnet repos: escaped, length-bounded, data only.
The delivery watermark lives in this module's ledger (never in the fleet
store); ledger dedup keys are the fleet's own per-class dedup keys
(cluster: term+episode; watchlist: term+netuid+epoch; econ: range id), so
even a watermark reset cannot double-send. Extraction runs in the fleet
unit and this scan runs in the repo unit — delivery may lag extraction by
up to one cycle by design.

**Gate-crossing alerts** page confirmed crossings only (livedata applies
the hysteresis and 2-poll confirmation before an event exists). The body
is single-fact `·` lines — netuid, demand share, bar, relative margin —
and names each figure's source (`shares: TaoSwap panel · bar: chain RPC ·
block N`), plus an `emission is DISABLED` note when the crossing subnet
earns zero either way. Both directions page (a cliff either way);
`cooldown_hours` (per netuid, default 24) records further events in the
ledger as `suppressed` instead of paging — never dropped. The watermark is
the livedata `gate_events` row id.

**Repository alert tiering** (signal-tiering, 2026-07-13). Each tracked commit
range is classified from recorded facts (changed paths + the recorded runtime
`spec_version` delta), deny-by-default:

- **Significant** — a `spec_version` bump, any touch of `pallets/ runtime/
  precompiles/ common/`, any top-level directory *not* in the churn allowlist,
  or an incomplete record (truncated / non-fast-forward). Pages immediately
  with an **interpreted breakdown** and states both clocks: `repo spec N ·
  live Finney spec M · Δ · not enacted on chain`. The breakdown leads with a
  one-line **verdict** (a runtime spec bump, a new/unmapped area, a light
  protocol touch amid a large sync, or a core protocol change), then splits
  **signal from noise**: a `protocol changed` line with per-area file counts
  and line churn `+adds/-dels`, pallets named with what they govern, unknown
  directories surfaced on their own line (never hidden), housekeeping listed
  separately with counts only, and a commit list filtered to substantive
  subjects (merge / CI / test dropped). Truncated ranges render lower-bound
  markers and a low-confidence verdict. The display taxonomy is code-defaulted
  and overridable via `area_map` / `pallet_map` / `light_touch_ratio` in
  [config.json](config.json); it affects wording only, never paging.
- **Churn** — ranges touching *only* the allowlist (`.github/ docs/ website/
  vendor/ sdk/`) with no spec change. Never paged, never dropped: written to
  durable `pending_churn` before the watermark passes, carried as a one-line
  digest on the next significant alert, or flushed by a periodic backstop.

The tier directory sets, the backstop cadence, and the governance threshold
live in [config.json](config.json). Every repo alert is badged a source-code
event, distinct from the live chain; a repo advance never implies the chain
moved. Messages render as Telegram HTML (escaped, size-bounded, single-fact
lines, no em dashes); an HTTP 400 falls back once to plain text, recorded.

**Guarantees**

- **Scrub, don't truncate** (ATLAS-TG-004): every message passes
  `assert_sendable`, which refuses — never masks-and-sends — if it matches
  the pinned inventory redaction oracle or contains the registered bot
  token.
- **Delivery ledger** (ATLAS-TG-005): the `events` table carries
  `event_id`, `created_at`, `attempted_at`, `status`, `retry_count`,
  `final_failure`. De-duplication is by stable `event_id` within
  `coalesce_window_seconds`, so a flapping source cannot flood the operator.
- **Isolation**: a Telegram outage, bad token, or API rejection is caught at
  the per-event boundary, recorded as `failed` after bounded retries, and
  never propagated — Hermes conversation, the repo timer, and live-data
  tools are unaffected.
- **Secrets**: the token is resolved from the operator's env files (the
  wizard-written `~/.hermes/.env` is reused, not duplicated) and registered
  for redaction; it never appears in a message, error, or ledger record.

**Extensibility**: the scan loop and ledger are class-agnostic — adding
`service-failure` later (once Hermes has a service unit) is a new adapter
entry only.

## Commands

```bash
python telegram/atlas_telegram.py init                       # seed watermarks to now (no sends) — run ONCE at deploy
python telegram/atlas_telegram.py scan                       # deliver new events
python telegram/atlas_telegram.py test --class schema-drift  # one test alert
python telegram/atlas_telegram.py status                     # ledger + watermarks
```

Run `init` before enabling any schedule, or the first `scan` treats the
whole backlog as new. Re-run `init` after an upgrade to seed only new classes
(it never rolls a seeded watermark back); the pre-tiering SHA-valued
repository watermark migrates itself to a `change_ranges.id` on the first
scan (no history replay). **Schedule (decided 2026-07-12; gate poll added 2026-07-28):** the hourly
`atlas-repotrack-update.service` runs three best-effort `ExecStartPost=-…`
steps after the repo update — `livedata/atlas_live.py poll-chain-head`
(one non-interactive TaoStats call so a live upgrade is detected promptly),
then `livedata/atlas_live.py poll-gate` (the emission-gate pass; inert
unless `gate_signal.enabled`), then `atlas_telegram.py scan`. The ordering
matters: each poll records fresh events *before* the scan reads them, so
they alert in the same run. All are best-effort — a notifier or provider
failure never fails the repo unit (isolation).

Config: [config.json](config.json). Setup: [docs/operator-setup.md](docs/operator-setup.md).
Tests: `python -m pytest telegram/tests -q` (or `python3 -m unittest discover
-s telegram/tests` where pytest is absent, e.g. the Pi's system Python).
