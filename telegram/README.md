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
| `chain-parameter-change` | `var/livedata/livedata.db` (`chain_param_events`) | a root-settable economic knob changed value (change: network-drift-443): the three emission-gate bar parameters plus the basket knobs (`BasketConcentrationCap`, the `swap_basket` buy cap, since root-weight-drift; the retired `RootWeightSettingEnabled` curation switch is no longer watched). Instant tier, **no cooldown and no digest** — such a knob cannot burst, and suppressing a second flip would be the wrong failure. A bar-parameter transition also states that the bar was re-priced for every subnet and that per-subnet crossing pages were withheld for that pass |
| `gate-crossing` | `var/livedata/livedata.db` (`gate_events`) | a subnet's demand share crossed the emission-gate bar in either direction (change: gate-crossing-signal) — an economic cliff event; instant tier with a per-netuid cooldown. Since network-drift-443 the body also names the active bar mode (rank-pinned or q-mass) and the bar's own movement, attributing the crossing to the bar when the bar alone accounts for it. Since rotation-signal-gate a crossing pages only once livedata marks it `eligible`: one reversed inside the 48h durability window is recorded and never paged, and one still `pending` holds the watermark for a later scan |
| `fleet-signal` | `var/fleet/fleet.db` (`signal_events`, read **strictly read-only**) | fleet-signals queue (change: fleet-signals): `watchlist` pages immediately, `narrative-cluster` is registered `shadow` and sends nothing (change: telegram-alert-redesign), `econ-code` is registered `shadow` and sends nothing; only a `high` verdict is emitted as `econ-code`, every other econ event as `econ-code-minor` (also `shadow`) (change: alert-tier-trim); `signal-digest` rows take their source class's tier from the dedup-key prefix, and only lines from an `instant` class are held in `pending_signal`, ride the next instant fleet alert, or flush via `digest_backstop_hours` |
| `repository-update` | `var/repotrack/repotrack.db` (`change_ranges`) | a **significant** tracked commit range (Phase 3 timer); churn is digested, not paged |
| `schema-drift` | `var/livedata/livedata.db` (`integration_health`) | a live provider response stopped validating (Phase 4) |
| `knowledge-ingestion` | `var/knowledge/knowledge.db` (`intake_runs`) | a new ingest run staged units for review (Phase 2) |
| `subnet-registry` | `var/livedata/livedata.db` (`panel_snapshot`) | a netuid appears, disappears, or changes its on-chain name between consecutive snapshots (change: pulse-briefing); the first snapshot seeds silently. Registrations and deregistrations page at `instant`; renames are emitted as `subnet-rename`, registered `shadow` (change: alert-tier-trim) |
| `fail-closed` | `var/livedata/livedata.db` (`integration_health`) | the gate poll or the chain-parameter watch has recorded only failures for longer than `window_hours` (change: pulse-briefing), keyed by the outage's first failure so a persisting outage pages once |

**Fleet signal alerts** name each subnet from the panel snapshot and
carry the term/subnet facts in the house layout (cluster: members, first
mover with date and `code` SHA, adoption window, fleet prevalence;
watchlist: term, source file, commit; econ-code: what changed, why it
matters, impact, then range SHAs, commit count, and matched files in the
fold) plus the entry price (alpha in TAO) when the fleet's price snapshot
is already recorded. A pending snapshot omits the price and never delays
delivery. Minor signals riding an instant alert are listed in its fold,
one per line. Terms and paths
originate in untrusted subnet repos: escaped, length-bounded, data only.
The delivery watermark lives in this module's ledger (never in the fleet
store); ledger dedup keys are the fleet's own per-class dedup keys
(cluster: term+episode; watchlist: term+netuid+epoch; econ: range id), so
even a watermark reset cannot double-send. Extraction runs in the fleet
unit and this scan runs on `atlas-alerts.timer`, so delivery may lag
extraction by up to one cycle by design.

**Gate-crossing alerts** page confirmed crossings only (livedata applies
the hysteresis and 2-poll confirmation before an event exists). The
headline names the subnet and direction. Key figures give the demand
share and its distance from the bar, the bar (as the Nth largest share in
rank mode), the cause (the subnet's demand or the bar moving), and the
alpha price at the event's block. The fold names each source (`Shares:
TaoSwap panel. Bar: chain RPC.`) and the block. A crossing on a subnet
with emission switched off renders as a short 🔵 note: it earns zero
either way. Both directions page (a cliff either way);
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
moved. Messages render as Telegram HTML in the house layout (canon:
[docs/voice.md](docs/voice.md) section 1a): severity marker, effect-first
headline, one meaning sentence, labelled key figures, provenance in an
expandable fold, `Next:` last. Values are escaped, bodies are sized before
rendering, and there are no em dashes. Links ride inline keyboard buttons
(`links` in [config.json](config.json)); link previews are off through
`link_preview_options`. An HTTP 400 resends once as plain text with the
same buttons, then once more without buttons; the fallback is recorded.

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

## Delivery tiers and the pulse briefing (change: pulse-briefing)

Every class carries a `tier`: `instant` pages on the scan that finds the
event; `briefing` records the event in the ledger with status `briefed`,
advances the watermark, and surfaces it only through the pulse briefing.
Every class carries a registered `tier` and a class the registry does not
name delivers nothing, so drift between the class list and the registry
fails closed. Three tiers: `instant` pages, `briefing` records as `briefed`
and rides the pulse edition, `shadow` records and is carried nowhere.
`shadow` is the default for a new netuid-scoped class, so nothing new can
page by accident. The tier is resolved per event, not per adapter, so the
three classes the fleet-signal queue emits are demotable independently.
Every processed event records the governing tier in the delivery ledger.
Flipping a tier value is the per-class rollback. `load_config` refuses a
`briefing` tier while `briefing.enabled` is false (change:
alert-tier-trim), so no class can be routed to an edition that is never
sent.

A class reaches a paging tier only by an operator decision recorded in
`docs/decisions.md` against a filled effectiveness read that beats the
fleet baseline (change: rotation-signal-gate). Demotion never stops
measurement, which is the only way a demotion can later be reversed on
evidence.

Two classes arrived with the briefing: `subnet-registry` (a netuid appears, disappears,
or changes its on-chain name between consecutive panel snapshots; the
first snapshot seeds silently) and `fail-closed` (one page per outage when
the gate poll or the chain-parameter watch has recorded only failures for
longer than `window_hours`, keyed by the outage's first failure). The
`chain-runtime-upgrade` message now joins the matching repository range
for the release subject and top touched areas, and states when none is
tracked yet. Crossings from a subnet flagged as hovering are recorded as
suppressed, never paged.

The briefing itself (`atlas_briefing.py`) is a daily edition at
`briefing.daily_hour_utc`, replaced weekly on `briefing.weekly_weekday`,
composed ONLY from stores already on disk (no provider call, no model
call). Each edition starts with ☀️ (daily) or 🗓️ (weekly) and a one-line
summary built by fixed rules. Then come network, chain rule changes,
biggest price moves, biggest demand-share moves, a watch list (the 3
non-immune subnets closest to deregistration, plus subnets at the bar),
and named high-impact incentive changes. Every line is a recorded fact
with its delta against the previous edition's persisted figures. System
health sits in an expandable fold. Edition watermarks in the ledger stop
double-sends; a missed hour catches up on the next scan that day.
Oversized editions shed the fold first, then whole lines from the
lowest-priority section upward (network is never cut), and state the
omission count. The last line is the next action when one exists. There
is no board link.

## Commands

```bash
python telegram/atlas_telegram.py init                       # seed watermarks to now (no sends) — run ONCE at deploy
python telegram/atlas_telegram.py scan                       # deliver new events
python telegram/atlas_telegram.py test --class schema-drift  # one test alert
python telegram/atlas_telegram.py status                     # ledger + watermarks
python telegram/atlas_telegram.py health                     # retry queue, then health checks
python telegram/atlas_telegram.py unit-failed atlas-fleet.service  # what OnFailure= runs
```

Run `init` before enabling any schedule, or the first `scan` treats the
whole backlog as new. Re-run `init` after an upgrade to seed only new classes
(it never rolls a seeded watermark back); the pre-tiering SHA-valued
repository watermark migrates itself to a `change_ranges.id` on the first
scan (no history replay). **Schedule (change: alert-delivery-reliability, 2026-11-03):**
`atlas-alerts.timer` runs hourly at :15. Its oneshot runs
`livedata/atlas_live.py poll-gate` first (a failure there is ignored), then
`atlas_telegram.py scan`. The scan used to ride the repo update as
`ExecStartPost` steps, so a failed fetch skipped every alert.

## Delivery reliability (change: alert-delivery-reliability)

- **Retry queue.** A send that fails on a network error, a 5xx or a 429
  is kept in `pending_send` with its rendered text, HTML and buttons. The
  next scan or health run resends it as-is, with a "Late send. Detected
  ..." line on top. Entries expire after 24 hours as `failed`. A 429 sets
  `meta.rate_limited_until` from `retry_after`, and every sender holds
  until then. 400, 401, 403 and 404 are final. Digests and briefing parts
  are never queued: their own state already re-sends them.
- **Ledger.** A delivered row keeps the sent text and the Telegram
  `message_id`. The probe, the upgrade job, the health watch and the unit
  failure notifier all send through `send_alert`, so they share the ledger,
  scrubber and queue.
- **Withheld notice.** A message the scrubber refuses is final. One fixed
  notice names its class and event id, and none of its text.
- **Health watch.** `atlas-health.timer` runs `health` every 5 minutes,
  outside Hermes. It pages once per outage, and once more on recovery,
  for:
  - the Hermes gateway: unit state, restart count, and
    `~/.hermes/gateway_state.json`. It pages after 2 failed checks in a
    row, so a `/restart` stays quiet;
  - the alert scan: no completed scan for 3 hours;
  - the LLM: a Claude auth failure in the Hermes logs newer than the last
    model reply, or 2 or more rewrite fallbacks for a model error in a row
    within 2 hours.

  The thresholds are in `health` in `config.json`, with the defaults in
  `atlas_health.py`.
- **Unit failures.** Every Atlas unit names
  `OnFailure=atlas-notify-failure@%n.service`. The dashboard, a system
  unit, uses `atlas-notify-failure-sys@`. Each unit pages once per failure
  streak, and the health watch ends the streak after a successful run.
  Handled outcomes exit 0, so a unit failure means a crash: the upgrade
  job after a reported failure or an RPC blip, and the probe watch after
  a drift page.
- **After a Hermes update:** check that `gateway_state.json` still has
  `gateway_state`, `pid`, `updated_at` and `platforms.telegram`, and that
  `agent.log` still logs `API call #N: model=`. If the shape changed, the
  watch pages "cannot read gateway state" and the LLM check falls back to
  rewrite outcomes.

Config: [config.json](config.json). Setup: [docs/operator-setup.md](docs/operator-setup.md).
Tests: `python -m pytest telegram/tests -q` (or `python3 -m unittest discover
-s telegram/tests` where pytest is absent, e.g. the Pi's system Python).
