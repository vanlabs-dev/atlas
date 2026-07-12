# livedata — TaoSwap/TaoStats live data (Phase 4, IN PROGRESS)

Fail-closed live Bittensor data (PRD §12.7 ATLAS-API-001…008, §12.8
ATLAS-LIVE-001…009; decisions Q24–30 incl. the 2026-07-12 refinements:
TaoSwap-first, no TaoStats spend on price checking, pacing headroom).

Status: plumbing + contract discovery. Adapters, schemas, and the
`atlas-live` MCP server land after the discovery operator gates
(tasks 2.3/4.3/5.3) — ATLAS-API-002 forbids building adapters before
real validated calls, and ATLAS-LIVE-002 forbids invented freshness
thresholds.

## Discovery

```
python3 livedata/discover_taoswap.py         # keyless, first
python3 livedata/discover_taostats.py \      # on the Pi (key in .env),
    --taoswap-report var/livedata/contract-taoswap-<run>.json
```

Both write ATLAS-API-003 contract reports (JSON + MD, 0600) to
`var/livedata/`. TaoStats discovery runs under a hard ≤ 40-call budget
through the persisted quota ledger (self-cap 2/min, 15s spacing — the
free-tier design target with headroom). The TaoStats report includes the
Q25/Q27 comparison the operator picks endpoints from.

## Store

`var/livedata/livedata.db`: `calls` (quota ledger), `audit` (the
Q29/LIVE-009 per-call record), `integration_health`, `response_cache`
(size-capped, labelled `historical-snapshot`), `provider_limits`
(provider-reported vs local estimates).

## Secrets

`TAOSTATS_API_KEY` from the repo-root `.env` (0600; template
`env.example`). Every error/report/audit path passes through redaction;
the key never appears in any output (ATLAS-API-008).
