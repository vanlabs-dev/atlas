# Atlas knowledge base (Phase 2)

Validated Bittensor knowledge on the Pi, per ATLAS-KB-001…010,
ATLAS-RET-001…007, and ATLAS-TOOL-001…004 via OpenSpec change
`atlas-phase-2-knowledge-base`. The corpus is the operator-confirmed July
2026 grounding trio (decision 2026-07-12), snapshotted in
[corpus/](corpus/SOURCES.md) with verified hashes.

## The pieces

| file | role |
|---|---|
| [`corpus/`](corpus/SOURCES.md) | verbatim snapshot + provenance + re-sync procedure |
| [`supersession-markers.json`](supersession-markers.json) | known-stale claims marked `conflicting` at ingest (currently: none — the 2026-07-28 re-sync absorbed all markers) |
| [`atlas_kb.py`](atlas_kb.py) | `ingest` (hash-verified, stages units + validation report) · `activate` (operator gate) · `status` |
| [`atlas_kb_server.py`](atlas_kb_server.py) | stdio MCP server: `knowledge_search` / `knowledge_get_evidence` / `knowledge_status` — replaces `atlas-test` |
| [`benchmark/`](benchmark/) | 30-exchange retrieval benchmark (battery, scorer, threshold sheet) — closes the deferred ATLAS-HERMES-003 retrieval criterion and re-tests MV-RI-4 |

## How knowledge flows

1. `python3 knowledge/atlas_kb.py ingest` — verifies corpus hashes,
   splits `##`-level units (~22) with provenance (source+hash, heading
   path, line range, coverage date, temporal scope), marks known
   conflicts, scans for secrets, writes the validation report, stages
   everything **inactive**.
2. Operator reviews the report and runs
   `python3 knowledge/atlas_kb.py activate --run <id>` (audited; prior
   runs deactivate).
3. Hermes queries the three read-only tools. Zero hits →structured
   `insufficient-evidence`; `conflicting` units always carry their
   conflict note; errors are ATLAS-TOOL-002 structured. The store opens
   `mode=ro`; the server's only write is a size-capped redacted audit
   line per call.

## The benchmark (acceptance gate)

33 tagged exchanges through live Hermes with the knowledge toolset:
22 grounded (exact/paraphrase/historical/conflict, markers + tool-call
required) and 11 refusal (unsupported/adversarial, the MV-RI-4 re-test:
dated corpus facts or explicit refusal, never a value presented as live).
Reuses the generalized model-validation machinery (runner
`hermes/modelval/run_battery.py --battery knowledge/benchmark/atlas_kb_battery.py`,
tag scoring from `state.db`, threshold sheet, exceptions, exit codes
0/3/4/1). Thresholds: [benchmark/docs/thresholds.md](benchmark/docs/thresholds.md)
(operator-approved before acceptance).

```sh
# on the Pi, after ingest + activate + Hermes config points at atlas-kb:
python3 hermes/modelval/run_battery.py \
    --battery knowledge/benchmark/atlas_kb_battery.py \
    --toolsets-tc atlas-kb --toolsets-plain atlas-kb \
    --tool-sets exact,paraphrase,historical,conflict,unsupported,adversarial
python3 knowledge/benchmark/atlas_kb_score.py score
```

(All sets run with the knowledge tool available — that is the realistic
deployment; the adversarial sets test that its dated answers are never
passed off as live.)

## Hermes registration (replacing atlas-test)

```yaml
mcp_servers:
  atlas-kb:
    command: python3
    args: ["/home/pi/atlas/knowledge/atlas_kb_server.py"]
    enabled: true
```

Remove the `atlas-test` entry — the baseline spec always said the test
tool would be replaced, not extended.

## Tests

```sh
cd knowledge/tests && python3 -m unittest discover -v
```

Off-device (WSL) against the real corpus snapshot and fixture session
stores; the Pi benchmark run is the acceptance run.
