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
| [`unit-kinds.json`](unit-kinds.json) | heading path to unit kind (`correction`, `procedure`; unmapped = `fact`); `procedure` units are stored but never searched; every entry must match a real heading (tested) |
| [`supersession-markers.json`](supersession-markers.json) | known-stale claims marked `conflicting` at ingest (currently: none — the 2026-07-28 re-sync absorbed all markers) |
| [`atlas_kb.py`](atlas_kb.py) | `ingest` (hash-verified, stages units + validation report) · `activate` (operator gate) · `status` |
| [`atlas_kb_server.py`](atlas_kb_server.py) | stdio MCP server: `knowledge_search` / `knowledge_get_evidence` / `knowledge_status` — replaces `atlas-test` |
| [`benchmark/retrieval_eval.json`](benchmark/retrieval_eval.json) | retrieval evaluation: each query must find its marker text in the top 5 results (test `test_retrieval.py`; the upgrade job's test gate runs it) |
| [`polarity-rules.json`](polarity-rules.json) | corpus polarity lint: claims the subtensor source refutes (subnet lock recycled, UID registration TAO burned, ...); a fact unit stating one fails `test_polarity.py` |
| [`benchmark/`](benchmark/) | 43-exchange retrieval benchmark (battery, scorer, threshold sheet) — closes the deferred ATLAS-HERMES-003 retrieval criterion and re-tests MV-RI-4 |

## How knowledge flows

1. `python3 knowledge/atlas_kb.py ingest` verifies corpus hashes and
   splits block units (about 315): one top-level bullet, numbered item,
   bold-led entry or paragraph per unit, inside its `#`/`##`/`###`
   section, with nested lines kept and blocks over 1,500 characters split
   at their nested items. Each unit carries provenance (source and hash,
   heading path, line range, coverage date, temporal scope including ISO
   dates) and a kind. Ingest marks known conflicts, scans for secrets,
   writes the validation report, and stages everything **inactive**. It
   writes no search index. Unit ids are `<file>::<heading path>#<n>` and
   are valid for the run that holds them.
2. Operator reviews the report and runs
   `python3 knowledge/atlas_kb.py activate --run <id>` (audited; prior
   runs deactivate). Activation rebuilds the search index in the same
   transaction: FTS5 with Porter stemming, the active run's `fact` and
   `correction` units only, `index_version` 2 in `kb_meta`. A failed
   rebuild rolls the activation back. `status` prints the index version.
3. Hermes queries the three read-only tools. `knowledge_search` drops
   stopwords and question words, expands `SN82` to subnet/netuid forms,
   ranks units with all terms first and fills with any-term units (bm25,
   heading weighted 8 to 1), and returns 5 results by default (max 10):
   run id and coverage date once, then per unit its id, kind, source,
   heading path, lines, temporal scope, evidence state, content (capped
   at 1,500 characters) and any conflict note. `knowledge_get_evidence`
   adds the full section text. A store from before change
   `knowledge-retrieval` is still served (no kind filter, old index)
   until its next activation. Zero hits: structured
   `insufficient-evidence`; `conflicting` units always carry their
   conflict note; errors are ATLAS-TOOL-002 structured. The store opens
   `mode=ro`; the server's only write is a size-capped redacted audit
   line per call.

## The benchmark (acceptance gate)

43 tagged exchanges (battery 0.2.0, re-baselined at spec 486) through
live Hermes with the production Atlas tool set: 32 grounded
(exact/paraphrase/historical/conflict, markers + knowledge-tool call
required) and 11 refusal (unsupported/adversarial, the MV-RI-4 re-test).
Markers match at word boundaries ("41" never matches "441"). A refusal
answer auto-passes only with no asked-for value, or with a value from a
live tool in the same exchange; everything else needs `--classify`.

Two checks need no model and run in every test run, including the
upgrade job's sandboxed test gate: every marker group must appear in the
corpus (`test_import_surface.py`), and every grounded exchange must be
answerable from the top 5 search results (`test_battery_retrieval.py`).
A corpus edit that drops a battery fact therefore blocks before the push;
re-baseline the battery when a spec retires a tested fact.
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

Every `hermes -z` session loads all enabled Atlas MCP servers whatever
`--toolsets-*` says (WP10 trace), so the battery measures the production
tool set: a live-sourced value on an adversarial question is a correct
answer, and the scorer checks for the live-tool call.

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
