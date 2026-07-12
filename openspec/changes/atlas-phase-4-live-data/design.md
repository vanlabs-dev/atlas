# Design: atlas-phase-4-live-data

## Context

Three accepted patterns carry this phase: the stdlib stdio MCP server
shape Hermes demonstrably calls (`atlas-kb`, `atlas-repo`), SQLite
single-file stores with fail-closed verdicts and 0600 redacted outputs in
gitignored `var/`, and fixture-based off-device tests with the Pi run as
acceptance. Provider ground truth as of 2026-07-12: TaoSwap
(`api.taoswap.org`) is keyless with a published OpenAPI 3.0.3 schema at
`/schema/` (54 endpoints, all GETs anonymous — verified live:
`/price-history/`, `/network-stats/`); TaoStats (`api.taostats.io`) needs
an `Authorization: <key>` header — the key is installed on the Pi
(`~/atlas/.env`, 0600) and the **design target is the free tier: 5/min
and 10,000/day (operator) vs the PRD's "10,000/month" input — discovery
confirms the real window**; CoinGecko's keyless `simple/price` is the
approved TAO/USD external reference (Q30). ATLAS-LIVE-002 forbids
inventing freshness thresholds and ATLAS-API-002 forbids building
adapters before real authenticated calls succeed, so discovery is a hard
stage gate, not paperwork.

## Goals / Non-Goals

**Goals:**

- Contract reports for both providers from real calls (ATLAS-API-003),
  with the TaoStats report doubling as the "what does it add over
  TaoSwap?" comparison the operator picks endpoints from.
- Typed fail-closed adapters for the first slice (TAO price, subnets,
  metagraph/validators, network stats) with per-endpoint freshness
  envelopes, persisted TaoStats quota, and bounded observable retries.
- `atlas-live` MCP tools whose every answer carries provider, timing,
  units, validation and freshness status — or an honest `unavailable`.
- The TAO/USD cross-check with recorded tolerance and conflicting-result
  behavior (ATLAS-LIVE-005).

**Non-Goals:**

- Notifications (Phase 5), the ATLAS-OPS health contract (Phase 6).
- Any write/transaction path to any provider; wallet operations.
- Bulk historical backfills or local mirroring of provider datasets.
- TaoStats endpoints beyond what the comparison report justifies.
- WebSocket/streaming feeds — polling GETs only in this phase.

## Decisions

1. **Layout**: top-level `livedata/` — `discover_taoswap.py` /
   `discover_taostats.py` (contract discovery, report-writing),
   `atlas_live.py` (adapters, validation, freshness, quota, store),
   `atlas_live_server.py` (stdio MCP), `schemas/` (pinned per-endpoint
   JSON schemas + `contract-version`), `config.json` (endpoints,
   freshness envelopes, tolerances, budgets — values filled from approved
   discovery), `tests/`, `README.md`. Stdlib only (`urllib`, `sqlite3`,
   `json`), same as every accepted module.

2. **Discovery is executable and budgeted** (ATLAS-API-001…005).
   Stage 1 TaoSwap: fetch `/schema/`, exercise the first-slice endpoints
   plus pagination/empty/error cases, record rate-limit headers and
   observed cadence (ATLAS-LIVE-007 — absence of a documented limit is
   recorded as "unknown, be polite: serial calls, ≥1s spacing", never
   "unlimited"). Stage 2 TaoStats: hard cap ≤ 40 calls at ≤ 4/min for the
   whole discovery, covering the four Q25 endpoints + negative tests
   (bad/missing auth, bad param, nonexistent resource) and confirming the
   real quota window (day vs month) from documentation + response
   headers. Both write ATLAS-API-003 reports (JSON + rendered MD, 0600,
   `var/livedata/`); multiple samples where shapes can vary
   (ATLAS-API-004). **Operator gates**: approve the TaoSwap freshness
   sheet; pick the TaoStats endpoint set from the comparison; approve the
   TAO/USD tolerance.

3. **Validation is pinned JSON-schema-per-endpoint, stdlib-checked**
   (ATLAS-API-006): each adapter validates structure, types, nullability,
   and units against `schemas/<provider>/<operation>.v1.schema.json`
   derived from docs + observed samples, before any value leaves the
   adapter. A validation failure = schema drift (ATLAS-API-007): fail
   closed, retain audit metadata per Q29 (never the body as trusted
   data), write an `integration_health` event, report drift.

4. **Freshness envelopes live in config, sourced from discovery**
   (ATLAS-LIVE-001/002/004): per operation — `must_hit_provider` (true
   for everything in the first slice), max upstream-timestamp age, max
   local-response age, expected update cadence. Requests with
   current/latest/now semantics are fresh calls by definition of the tool
   surface (each tool IS a live operation — there is no cached variant to
   accidentally serve). On failure the tool returns structured
   `live-unavailable` with the failure category and the age of the last
   good response *as metadata only* — the cached value itself is returned
   only by an explicit `include_last_known: true` argument and arrives
   labelled `historical-snapshot`, satisfying LIVE-004 without a second
   tool.

5. **Quota manager is a persisted token ledger** (ATLAS-LIVE-006): SQLite
   table of call timestamps per provider; per-minute sliding window and
   per-window (day or month, as confirmed) counters checked before every
   TaoStats call. **The per-minute self-cap sits BELOW the provider
   limit** (operator refinement 2026-07-12: leave headroom, never fill
   5/min — proposed self-cap 2/min, operator-approved at the 5.3 gate),
   with a configurable interactive reserve (default: refuse
   non-interactive use above 80% of window). Provider-reported limit
   headers, when observed, are stored alongside and reported as
   authoritative vs the local estimate. At capacity: visible structured
   `quota-exhausted` failure. TaoSwap and CoinGecko get the same ledger
   with politeness budgets (serial, spaced) since neither is assumed
   unlimited.

6. **Retries are per-endpoint constants, observable, and stingy**
   (ATLAS-LIVE-008): idempotent GETs only; at most 1 retry with jitter on
   connect/5xx; **never** on 429 or schema-drift; TaoStats retries also
   consume quota so they count against the ledger. Every attempt lands in
   the audit log.

7. **MCP server `atlas-live` follows the accepted server shape** with
   five named tools (ATLAS-TOOL-002/003/004): `live_price()` (the
   cross-checked TAO/USD from **TaoSwap + CoinGecko only — it never
   spends TaoStats quota** per the Q30 refinement; conflicting
   results marked per ATLAS-LIVE-005), `live_subnets(netuid?)`,
   `live_metagraph(netuid)`, `live_network_stats()`, `live_status()`
   (integration health events, quota remaining local-vs-reported,
   last-success per provider). Every success carries the full
   ATLAS-LIVE-003 metadata envelope. No generic query/URL/SQL surface.
   Append-only redacted JSONL audit with the standard size-capped
   rotation; the audit record set is exactly the Q29/LIVE-009 list.

8. **Secrets** (ATLAS-API-008): `.env` parsed by a tiny loader (no
   dependency), key held in process memory only, redaction applied to
   every error/report/audit path via the pinned `inv.redact` machinery,
   never echoed by any tool, rotation = replace `.env` line + restart.

9. **Cross-check scope stays one value, two providers** (Q30 refined):
   TAO/USD from TaoSwap (`/price-history/` latest point or better
   current-price endpoint if discovery finds one) and CoinGecko
   `simple/price`. TaoStats `/api/price/latest/v1` is exercised once in
   discovery for the comparison report but is **not** part of production
   price checking — no quota spent there. Comparison rule: pairwise
   relative deviation vs the operator-approved tolerance; disagreement →
   all values + sources + `conflicting: true`, logged as a health event.
   No averaging, no winner-picking (ATLAS-LIVE-005 applies to whichever
   providers contributed).

10. **Testing mirrors the accepted pattern** (Q28): a stdlib
    `http.server` fixture provider replays recorded, redacted, pinned
    responses off-device — covering happy paths, empty/paginated shapes,
    schema drift, 429/5xx, timeouts (controlled path per ATLAS-API-005),
    quota exhaustion and restart persistence, disagreement and tolerance.
    Real-call verification is discovery (ATLAS-API-002) + Pi acceptance.
    The §16 exit criteria map 1:1 onto acceptance checks, including a
    dead-proxy outage run (the Phase 3 trick) and a quota-ledger restart
    test.

11. **Conviction enactment bonus check**: if discovery finds a
    runtime/spec endpoint (chain `spec_version`), acceptance records
    whether mainnet ≥ 425 — closing the "enactment date" tail of the
    2026-07-12 conviction decision. Nice-to-have, not an exit criterion.

## Risks / Trade-offs

- [TaoSwap has no documented rate limit] → treated as unknown, not
  unlimited (LIVE-007): serial spaced calls, politeness budget in the
  same ledger, back off on any 429/503.
- [Free-tier window ambiguity (10k/day vs month)] → discovery confirms
  from docs/headers; the ledger is window-agnostic config so either value
  drops in; until confirmed the stricter reading (month) bounds
  non-interactive use.
- [TaoSwap price is daily-granularity if no spot endpoint exists] → the
  discovery report says so explicitly; freshness envelope then reflects
  daily cadence and the cross-check leans on CoinGecko/TaoStats for spot;
  never presented fresher than its upstream timestamp.
- [Provider ToS constraints on caching/storage] → ATLAS-API-003 requires
  recording terms; Q29 retention (metadata + hashes, small labelled
  cache) is conservative by design.
- [Schema drift breaks answers mid-phase-5+] → that is the designed
  behavior: fail closed + health event + visible in `live_status()`;
  repair = re-run discovery for that endpoint, bump pinned schema
  version, tests re-pin.
- [Quota ledger and wall-clock skew] → timestamps from the Pi's NTP-synced
  clock; windows computed UTC; ledger prunes old entries; provider
  headers, when present, override local estimates in reporting.
- [Three providers = three failure surfaces in one tool call for
  `live_price`] → per-provider isolation: one provider failing yields
  partial results with per-provider status, not a total failure; zero
  providers → `live-unavailable`.

## Open Questions

- TaoStats free-tier window: day or month (discovery confirms; ledger
  takes either).
- Whether TaoSwap exposes a true spot-price endpoint beyond daily
  `/price-history/` (discovery answers; affects the price freshness
  envelope).
- Final TaoStats endpoint set (operator picks from the comparison
  report — Q25/Q27 anticipate the four-candidate slice).
- TAO/USD disagreement tolerance value (operator approves; proposed
  starting point: 2% pairwise relative deviation).
- Hermes toolset identifier for the new server (expected `atlas-live`,
  pinned at on-device acceptance like the previous two).
