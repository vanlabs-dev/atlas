# livedata — TaoSwap/TaoStats/CoinGecko live data (Phase 4)

Fail-closed current Bittensor data for Hermes (PRD §12.7
ATLAS-API-001…008, §12.8 ATLAS-LIVE-001…009; decisions Q24–30 and the
Phase 4 discovery gates, all 2026-07-12). Providers: **TaoSwap first**
(keyless), **TaoStats** where it adds data (keyed, quota-budgeted),
**CoinGecko** as the TAO/USD spot reference. Production price checking
spends **no TaoStats quota** (Q30).

Interpreting emission, burn, and miner-economics fields from these
providers: [`docs/emission-metrics.md`](../docs/emission-metrics.md) —
verified constants, derivation formulas, and the fields that are empty or
misleading (`active_miners`, `block_at_registration`, `daily_rewards_alpha`).

## Module map

```
discover_taoswap.py    contract discovery, keyless (budget 30 calls)
discover_taostats.py   contract discovery, keyed (hard budget 40 calls,
                       paced through the ledger; run on the Pi)
discovery_common.py    shared probe/report machinery (ATLAS-API-003/004/005)
atlas_live.py          store, quota ledger, HTTP, pinned-schema validation,
                       per-operation adapters, the fail-closed pipeline;
                       also the `poll-chain-head` CLI (scheduled live-spec
                       poll), live `spec_version` upgrade recording, and
                       the `poll-gate` / `status` CLIs (emission-gate
                       state + crossing events, change: gate-crossing-signal)
atlas_live_server.py   `atlas-live` stdio MCP server (six tools)
schemas/               pinned per-endpoint schemas (drift = missing or
                       mistyped required field; extras tolerated)
config.json            operator-approved contract: endpoints, freshness
                       envelopes, budgets, tolerance (gates 2.3/4.3/5.3);
                       `gate_signal` block (kill-switch, pinned storage
                       keys, hysteresis policy)
tests/                 fixture-provider suite (68 tests, off-device)
```

## The pipeline (every live call)

quota/pacing acquire → HTTP GET (bounded retries: 1 retry on
connect/5xx, **never** on 429; per-provider timeout — TaoStats 45s,
observed spiky) → JSON parse → pinned-schema validation → typed
post-processing → ATLAS-LIVE-003 envelope (provider, operation, request
time, upstream timestamp, block reference, units, validation +
freshness status) → audit record (Q29 field set) + labelled cache.

Failures return structured `live-unavailable`. A cached value is
returned ONLY on explicit `include_last_known: true`, labelled
`historical-snapshot` with its age (ATLAS-LIVE-004). Schema drift fails
closed and writes an `integration_health` event (ATLAS-API-007).

## Quota (ATLAS-LIVE-006/007)

TaoStats free tier: 5/min, 10,000/**month**. Atlas self-caps at
**2/min** with 15s spacing (headroom by design — never fills the
provider limit) and refuses non-interactive use above **80%** of the
month. The ledger (`var/livedata/livedata.db`) persists across
restarts and distinguishes local estimates from provider-reported
headers. TaoSwap/CoinGecko have no documented limits — recorded as
UNKNOWN, politeness budgets applied (never assumed unlimited).

## Tools (`atlas-live`)

`live_price` (CoinGecko spot + TaoSwap daily close, cross-checked at 5%
pairwise tolerance; conflicts surfaced, never averaged, never
TaoStats), `live_subnets` (TaoSwap rich aggregates: emission share,
**emission_miner_burn 0–100%**, root_proportion, moving price, excess
TAO emission, flows, active_miners, identity/github, dereg, conviction;
optional TaoStats protocol params), `live_burn_leaderboard` (one-shot
TaoSwap burn ranking with filters), `live_metagraph` (**default TaoSwap
keyless** full neurons with incentive/emission; optional
`source=taostats`), `live_network_stats` (TaoSwap), `live_chain_head`
(default TaoStats for `spec_version`; optional `source=taoswap` block
head only), `live_portfolio` (TaoSwap coldkey balance + PnL/APY; ss58
or aliases SECURE/5FART/CRUSTY from `config.wallet_aliases`),
`live_status` (health events, quota, last successes; no provider
calls).

A validated `chain_head` response also persists the last-seen live
`spec_version` and writes a durable `spec_upgrades` event on any change
(from validated data only, idempotent across restarts). The
`poll-chain-head` CLI runs one such read on a schedule — piggybacked on the
hourly repotrack service, *before* the Telegram scan — so a live runtime
upgrade is detected promptly rather than only when Hermes happens to query.
The Telegram `chain-runtime-upgrade` alert class reads that event store
read-only; no extra TaoStats quota is spent by the notifier.

**Emission-gate poll** (change: gate-crossing-signal, live 2026-07-28;
extended by network-drift-443, live 2026-08-06). `poll-gate` reads the
gate state — the bar theta (`EmissionGateBar`) plus the sudo-settable
rank N (`EmissionBarRank`), q (`EmissionBarQuantile`) and h
(`EmissionGateExponent`) — from finney via keyless allowlisted JSON-RPC
`state_getStorage` on pinned pre-verified keys, all at one finalized
block (endpoint: `entrypoint-finney.opentensor.ai`). Each item decodes
with its own declared codec: theta/q/h are `U64F64`, N is a SCALE `u16`.
Null storage is a defined state: null N/q/h persists the documented
per-runtime default marked `assumed-default`, null/zero theta persists
gate-inactive.

Since spec 441 (2026-08-03) N selects how the bar is found: N > 0 pins
theta to the Nth-largest positive demand share and makes q **inert**;
N = 0 is the old q-mass fallback. Every observation therefore records its
derived `bar_mode` (`rank` | `q-mass`), so a crossing stays interpretable
with the mode of its own pass rather than whatever the bar is doing
later. Live Finney: N unset, so the v443 code default of 32 applies and
rank mode is active while q sits explicit at 0.75, unused.

Because a rank-pinned bar is itself a demand share, it moves on its own,
so each crossing also records the previous observation's theta and the
notifier attributes a crossing to the bar when the bar's movement alone
accounts for it. A change to any bar parameter re-prices the bar for
every subnet at once, which would otherwise emit exactly |M - N|
simultaneous crossings (this happened at the spec-441 bar reset on
2026-08-03: four subnets paged as rising when the bar had fallen onto
them). Such a pass now **re-seeds every side silently** and the
chain-parameter alert carries the story instead.

Rank mode also supplies a free correctness check: exactly N positive
shares sit at or above the bar, so each rank-mode pass persists
`above_count` beside the effective N and records an
`invariant-divergence` health event when they disagree beyond
`above_count_tolerance`. The count comes from the computed shares, not
from tracked sides, so hysteresis cannot masquerade as disagreement. It
never suppresses events or discards a pass. Demand shares come
from the `subnets_taoswap` panel of the same pass, normalized over ALL
non-root subnets (the chain's bar universe includes emission-disabled
subnets — they are zeroed only after gating). Per-netuid sides flip only
after the share exits a ±`hysteresis_pct` band around theta on
`confirm_polls` consecutive polls; first sight seeds silently, absence
for `absence_clear_polls` clears a side (netuid-reuse guard), and a
gate-inactive→active transition re-seeds everything silently. Confirmed
crossings land in `gate_events`; the Telegram `gate-crossing` class reads
them read-only by row id. Kill-switch: `gate_signal.enabled` in
[config.json](config.json).

**Chain-parameter watch** (change: network-drift-443, live 2026-08-06).
Discrete root-settable knobs whose flip changes network economics with no
AdminUtils extrinsic trail. The three bar parameters are handed over
already decoded by the gate poll — one storage read per item, one durable
history — while `RootWeightSettingEnabled` (the Root Reborn basket
curation master switch, currently `false`, so dividends accumulate in
place) is read on its own pinned key at the same finalized block. Each
pass persists one observation per item with `explicit` or
`assumed-default` provenance; a differing value records a durable
transition. No hysteresis (these do not flap), a first observation seeds
without emitting one, and a provenance-only change at an unchanged value
is recorded but never paged. Independent items fail in isolation — one
unreadable knob does not blind the rest. The watch is deliberately **not**
gated by `gate_signal.enabled`: rolling back the gate signal must not
silently stop watching the curation switch. Transitions feed the Telegram
`chain-parameter-change` class. Kill-switch: `chain_params.enabled` in
[config.json](config.json).

```bash
python3 livedata/atlas_live.py poll-chain-head   # one validated chain-head read; records live spec + upgrade event
python3 livedata/atlas_live.py poll-gate         # one emission-gate pass: theta/N/q/h + shares -> crossing events + chain-param watch
python3 livedata/atlas_live.py status            # gate state (incl. bar mode) / sides / crossings / watched params + last live spec
```

Hermes registration (done 2026-07-12, alongside atlas-kb/atlas-repo):

```yaml
atlas-live:
  command: python3
  args: ["/home/pi/atlas/livedata/atlas_live_server.py"]
```

## Panel snapshot, vitals, and gate smoothing (change: pulse-briefing)

Each gate pass that validates the TaoSwap panel persists one
`panel_snapshot` row per non-root subnet (computed demand share plus the
panel fields the briefing reads; absent fields stay NULL, never zero),
pruned to `gate_signal.panel_snapshot_retention_days`. Once per UTC day
the poll also persists one `network_vitals` row from two keyless calls
(`network_stats_taoswap`, `price_daily_taoswap`); a failed or invalid
fetch records a health event and persists nothing for the day.

Side tracking treats a zero moving price as a panel gap, not a demand
reading: no crossing to or from zero, and the pass counts toward the
absence threshold. A subnet recording more than
`gate_signal.hover_crossings` crossings inside
`gate_signal.hover_window_days` is flagged hovering; its crossings still
record, carry a `hovering` annotation, and the flag clears only after a
full quiet window.

## Secrets

`TAOSTATS_API_KEY` from the repo-root `.env` (0600; template
`env.example`; os.environ fallback for tests). Every error/report/audit
path passes through redaction — including redaction of the key value
itself; reports are redacted tree-wise (never on serialized JSON).

## Re-discovery after drift

When a pinned schema drifts (health event + `live_status`): re-run the
provider's discovery script, review the new report, update the pinned
schema with a version bump, and record the change in
`docs/decisions.md`. TaoStats re-discovery stays inside the 40-call
budget.

## Tests

```
cd livedata/tests && python3 -m unittest discover -s .
```

A stdlib fixture provider replays schema-conformant responses and
exercises: envelopes, freshness (fresh/aged-upstream), drift, the
currency-echo guard (TaoSwap ignores bad params), 429 never-retry, 5xx
single-retry, quota exhaustion before HTTP, restart persistence,
snapshot opt-in labelling, disagreement marking, secret-leak
regression, and the server surface scan.
