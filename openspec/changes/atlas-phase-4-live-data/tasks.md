# Tasks: atlas-phase-4-live-data

TaoSwap first (keyless), TaoStats second (keyed, budgeted), per the
recorded Q26/27 ordering. Off-device work uses fixture providers; real
calls happen in discovery (ATLAS-API-002) and Pi acceptance. Operator
gates are explicit tasks — nothing is assumed before it is recorded in
[docs/decisions.md](../../../docs/decisions.md).

## 1. Scaffold and shared plumbing

- [ ] 1.1 Create `livedata/` scaffold: `atlas_live.py` (adapters/store/
      quota/freshness skeleton), `atlas_live_server.py` stub, `schemas/`,
      `config.json` (providers, endpoints, envelopes, tolerances, budgets
      — placeholders marked unconfirmed), `tests/`, `README.md`,
      following the accepted module conventions (stdlib-only,
      fail-closed, 0600 outputs under `var/livedata/`)
- [ ] 1.2 Implement the store (`var/livedata/livedata.db`): call ledger
      (quota windows), audit records (the Q29/LIVE-009 field set),
      `integration_health` events, size-capped labelled last-response
      cache; plus the `.env` loader with redaction wired through
      (ATLAS-API-008)
- [ ] 1.3 Implement the quota/politeness ledger: per-minute sliding
      window + configurable day/month window, persisted, interactive
      reserve policy, local-estimate vs provider-reported tracking,
      visible `quota-exhausted` failure; **TaoStats self-cap strictly
      below the provider's 5/min (proposed 2/min) — headroom by design**
      (ATLAS-LIVE-006/007, operator refinement)

## 2. Contract discovery — TaoSwap (keyless, first)

- [ ] 2.1 Implement `discover_taoswap.py`: pull `/schema/`, exercise the
      Q27 first-slice endpoints (price-history/spot if present, subnets,
      v2 validators, metagraph/{id}, network-stats, blocks) with multiple
      samples, pagination/empty shapes, safe negative tests, rate-header
      observation; write the ATLAS-API-003 report (JSON + MD, 0600)
- [ ] 2.2 Run TaoSwap discovery for real; record rate behavior from
      terms/headers/observation ("unknown → politeness policy" if
      undocumented, ATLAS-LIVE-007); note whether a true spot-price
      endpoint exists
- [ ] 2.3 **Operator gate**: approve the TaoSwap contract report and its
      proposed per-endpoint freshness envelopes; record in
      `docs/decisions.md`; pin approved values into `config.json`

## 3. TaoSwap adapters and validation

- [ ] 3.1 Pin per-endpoint JSON schemas (`schemas/taoswap/*.v1.schema.json`)
      from documented + observed samples; implement the stdlib validator
      (types, nullability, units) run before any exposure
      (ATLAS-API-006)
- [ ] 3.2 Implement the TaoSwap adapters for the approved slice with the
      LIVE-003 metadata envelope, freshness evaluation, bounded
      per-endpoint retries (never on 429/drift), drift → fail closed +
      health event (ATLAS-API-007, ATLAS-LIVE-008)
- [ ] 3.3 Off-device tests over a stdlib fixture provider: happy paths,
      empty/paginated shapes, schema drift, 429/5xx, timeout path,
      envelope violations (`aged-upstream`), retry observability

## 4. Contract discovery — TaoStats (keyed, budgeted) + comparison

- [ ] 4.1 Implement `discover_taostats.py`: hard cap ≤ 40 calls at
      ≤ 4/min through the quota ledger; cover the four Q25 candidates
      (`/api/price/latest/v1`, `/api/subnet/latest/v1`,
      `/api/metagraph/latest/v1`, `/api/block/v1`) + safe negative tests
      (missing/invalid auth, bad param, nonexistent resource); confirm
      the real free-tier window (day vs month) from docs + headers; check
      for a runtime/spec_version signal (conviction enactment bonus)
- [ ] 4.2 Run TaoStats discovery on the Pi (where the key lives); write
      the report **including the TaoSwap comparison**: per data category,
      what TaoStats adds (spot freshness, fields, block references)
- [ ] 4.3 **Operator gate**: from the comparison, pick the TaoStats
      endpoint set (may be smaller than the four); approve its freshness
      envelopes and the confirmed quota window; record in
      `docs/decisions.md`; pin into `config.json`
- [ ] 4.4 Pin TaoStats schemas + implement adapters for the chosen set
      behind the quota ledger (429 → no retry, ledger-aware), same
      envelope/drift behavior; extend fixture tests (quota exhaustion,
      restart persistence, auth-failure redaction)

## 5. Cross-check and MCP server

- [ ] 5.1 Implement the CoinGecko TAO/USD reference adapter (keyless
      `simple/price`, pinned schema, politeness budget) — reference use
      only, per Q30
- [ ] 5.2 Implement the `live_price` comparison over **TaoSwap +
      CoinGecko only (zero TaoStats quota — Q30 refinement; tested)**:
      pairwise relative deviation vs tolerance, partial-provider results
      with per-provider status, `conflicting: true` + logged discrepancy
      beyond tolerance, no averaging (ATLAS-LIVE-005)
- [ ] 5.3 **Operator gate**: approve the TAO/USD disagreement tolerance
      (proposed 2% pairwise), the interactive quota reserve (proposed
      80% cutoff for non-interactive), and the TaoStats per-minute
      self-cap (proposed 2/min, below the 5/min limit); record in
      `docs/decisions.md`
- [ ] 5.4 Implement `atlas_live_server.py` (stdio MCP, accepted shape):
      `live_price`, `live_subnets`, `live_metagraph`, `live_network_stats`,
      `live_status` — LIVE-003 envelopes, `live-unavailable` /
      `historical-snapshot` semantics (explicit opt-in only), structured
      errors, append-only redacted audit, no generic surface
- [ ] 5.5 Off-device server contract tests: metadata envelope on every
      success, unavailability on outage, snapshot only when requested and
      labelled, conflicting-price path, status tool (health + quota
      local-vs-reported), secret-leak regression (auth errors redacted),
      read-only surface scan

## 6. On-device acceptance (Pi)

- [ ] 6.1 `git pull`; run both discoveries' acceptance re-checks; verify
      `.env` loading and that no report/log contains key material
- [ ] 6.2 **Operator action**: register `atlas-live` in the Hermes config
      (alongside `atlas-kb`/`atlas-repo`), pin the toolset identifier
- [ ] 6.3 Exit-criteria battery through live Hermes (`-z`, `-t atlas-live`):
      current TAO price answered with provider + timestamp metadata;
      current subnet/metagraph question answered with envelope; outage
      run via dead proxy → honest unavailable (no stale substitution, no
      invented value — the MV-RI-4 class closed with a live path)
- [ ] 6.4 Quota persistence proof on-device: spend ledger calls, restart,
      verify carry-over; verify rate pacing matches the confirmed
      contracts (§16 exit criteria)
- [ ] 6.5 Conviction enactment check if discovery found a spec_version
      signal: record mainnet ≥ 425 (or its absence) in
      `docs/decisions.md`, closing the 2026-07-12 evidence-check tail

## 7. Documentation and close-out

- [ ] 7.1 Write `livedata/README.md`: discovery procedure and budgets,
      config/envelope/tolerance provenance, quota model, re-discovery
      after drift, server registration, test instructions
- [ ] 7.2 Update `README.md` (status, layout, next step → Phase 5) and
      `docs/decisions.md` acceptance entry (runs, spent quota, exit
      criteria, deviations); confirm remaining open items list
