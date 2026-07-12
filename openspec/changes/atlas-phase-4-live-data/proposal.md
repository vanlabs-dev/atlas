# Proposal: atlas-phase-4-live-data

Governing documents: [prd.md](../../../prd.md) (§12.7 ATLAS-API-001…008,
§12.8 ATLAS-LIVE-001…009, §12.10 ATLAS-TOOL-001…004, §16 Phase 4) and
[docs/decisions.md](../../../docs/decisions.md) Q24–30 (all decided
2026-07-12): **TaoSwap first** — `https://api.taoswap.org`, keyless, OpenAPI
at `/schema/`, verified live; TaoStats (`https://api.taostats.io`, key
installed in the Pi's 0600 `.env`) added only where a comparison shows it
adds data; **quota design target is the TaoStats FREE tier** (5/min,
10,000/day per the operator — the PRD's "10,000/month" phrasing is an
unconfirmed input; discovery confirms which); retention is typed values +
metadata/hashes with a size-capped redacted cache in `var/` (Q29 resolves
the ATLAS-LIVE-009 TBD); TAO/USD is the one cross-checked value, with
keyless CoinGecko as the approved external reference (Q30).

## Why

Atlas can answer from dated validated knowledge and cite subtensor source
by commit, but it still cannot answer a single *current* question — price,
subnet state, chain head — and the model-validation exception (MV-RI-4)
proved what happens when live data is absent: models invent it. Phase 4
gives Atlas fail-closed live adapters so "current" answers come from
validated provider responses with source and time metadata, or are refused
honestly — never guessed, never silently served from cache.

## What Changes

- **Contract discovery before any adapter** (ATLAS-API-001…005): an
  executable discovery script per provider making real calls — TaoSwap
  first (keyless; rate behavior documented from headers/terms/safe calls
  per ATLAS-LIVE-007, never assumed unlimited), then TaoStats under a hard
  discovery budget sized to the free tier. Each produces an ATLAS-API-003
  contract report (0600, `var/livedata/`) covering schema
  observed-vs-documented, units, timestamps, pagination, rate/error
  behavior, plus safe negative tests (ATLAS-API-005). **The TaoStats
  report doubles as the Q25/Q27 comparison: what does the keyed, limited
  provider add over keyless TaoSwap?** — the operator picks the TaoStats
  endpoint set from it.
- **Typed, fail-closed adapters** (`livedata/`): stdlib validators derived
  from confirmed documentation + observed responses; validation before
  anything reaches Hermes (ATLAS-API-006); schema drift → fail closed +
  integration-health event, never a guessed mapping (ATLAS-API-007);
  bounded, endpoint-specific, observable retries (ATLAS-LIVE-008).
- **Freshness envelopes from confirmed semantics** (ATLAS-LIVE-002): per
  endpoint — must-hit-provider, max upstream age, max local age, expected
  update frequency — proposed by the discovery reports and operator-
  approved; no invented thresholds. "Current/latest/now" always triggers a
  fresh call (ATLAS-LIVE-001); failures return **unavailable**, with any
  snapshot offered only as clearly labelled history on request
  (ATLAS-LIVE-004).
- **TaoStats quota manager** (ATLAS-LIVE-006): SQLite-persisted per-minute
  and per-day/month budgets (free-tier targets until discovery confirms
  the real window), surviving restarts, distinguishing local estimates
  from provider-reported headers, reserving interactive headroom, failing
  visibly at capacity. **Pacing leaves headroom by design (operator
  refinement): the self-imposed per-minute cap sits below the provider's
  5/min (proposed 2/min) — Atlas never tries to fill the limit.**
- **TAO/USD cross-check** (ATLAS-LIVE-005, Q30 as refined): **TaoSwap vs
  the CoinGecko keyless reference only — no TaoStats quota is ever spent
  on price checking** (its price endpoint appears solely in the one-off
  discovery comparison); disagreement beyond an operator-approved
  tolerance returns all values marked conflicting with source metadata,
  logged — never silently picking one.
- **Read-only live tools for Hermes** (`livedata/atlas_live_server.py`,
  stdio MCP `atlas-live`): named operations only (no generic query
  surface — ATLAS-TOOL-003) for the Q27 first slice: TAO price, subnets,
  metagraph/validators, network stats, plus an integration-health/quota
  status tool. Every successful result carries provider, operation,
  request time, upstream timestamp/block where available, units,
  validation and freshness status (ATLAS-LIVE-003); structured errors and
  an append-only redacted audit (ATLAS-TOOL-002/004, ATLAS-LIVE-009/Q29).
- **Secrets stay invisible** (ATLAS-API-008): key read from the 0600
  `.env`, redacted from logs/errors, never returned by any tool, never in
  Hermes memory, rotatable independently.
- Explicitly out of scope: Telegram notifications (Phase 5), the frontend
  health contract (Phase 6, ATLAS-OPS), any wallet-signing or transaction
  capability, historical bulk backfills, and adding TaoStats endpoints
  beyond what the comparison report justifies.

## Capabilities

### New Capabilities

- `live-data`: Fail-closed live Bittensor data on the Pi — contract-
  validated TaoSwap (keyless, first) and TaoStats (keyed, quota-budgeted)
  adapters with typed validation, per-endpoint freshness envelopes,
  persisted quota, bounded observable retries, TAO/USD cross-provider
  disagreement handling, and read-only Hermes MCP tools whose answers
  carry source and time metadata or state unavailability plainly.

### Modified Capabilities

None. (`knowledge-base` and `subtensor-repo-tracking` are untouched;
`atlas-live` is a third, separate MCP server following the same accepted
pattern.)

## Impact

- **Device**: new SQLite store + reports under gitignored `var/livedata/`;
  outbound HTTPS to `api.taoswap.org`, `api.taostats.io`, and
  `api.coingecko.com` (cross-check only); `.env` already holds the key.
  Inbound posture unchanged.
- **Repo**: new `livedata/` module (discovery scripts, adapters, quota,
  MCP server, schemas, tests) reusing the established conventions
  (stdlib-only, fail-closed, 0600 redacted outputs, fixture-based
  off-device tests).
- **Hermes**: gains a third stdio MCP server (`atlas-live`); registration
  is an operator-approved config edit like `atlas-kb`/`atlas-repo`.
- **Decisions**: resolves the day-vs-month free-tier question, the
  per-endpoint freshness sheet, the disagreement tolerance, and the final
  TaoStats endpoint set (operator approvals recorded during apply).
- **Downstream**: Phase 5 notifications get health/quota events to alert
  on; the conviction enactment question gets its chain-side check if
  discovery finds a runtime/spec endpoint; MV-RI-4-class questions gain a
  true live path, closing the last honesty gap.
