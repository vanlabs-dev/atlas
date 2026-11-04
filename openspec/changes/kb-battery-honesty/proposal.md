# Proposal

## Why

The knowledge battery cannot catch the failures it exists for. Re-verified 2026-11-05 (audit A5, A6, A8, and the WP5 carry-over).

- **Refusal scoring cannot fail.**
  - An answer passes the unsupported and adversarial sets on "as of", "snapshot" or "knowledge base", words SOUL puts into nearly every answer. So "TAO is $X as of today" passes.
  - The 2026-09-24 run passed every refusal through those words: "I do not know" is not a marker.
- **Markers reward stale or absent facts.**
  - KB-EX-1 accepts the 18/41 split, which is no longer the rule after spec 481.
  - "41" matches "spec 441".
  - KB-CF-5's markers have zero hits in the corpus.
  - KB-HI-3 and KB-UN-3 contradict each other on the dTAO date, which the corpus now states (2025-02-13).
  - The marker pin test (`test_expected_markers_pinned_against_corpus`) skips the conflict set, so KB-CF-5's dead markers pass. It also uses plain substring matching.
- **The corpus contradicted itself** on what happens to registration TAO (recycled, burned, seeds the pool) and nothing would catch a repeat (audit A10, second half).
- **No battery runs before activation.** The upgrade job activates corpus edits it wrote itself, and nothing checks that the battery's facts can still be retrieved.
- **The honesty contract covers numbers only** (SOUL and `agent-voice`). Mechanism claims such as commit-reveal, Yuma 3 or childkey take may come from model memory. Telegram made 5 `knowledge_search` calls since 2026-10-01.
- **The battery runner no longer matches the deployment.** Since WP10 we know a CLI `-z` session loads every enabled MCP server. A rerun therefore has `atlas-live`, and a correct live-sourced answer to "latest block" would be flagged.

## What Changes

- **Refusal scoring.**
  - An unsupported or adversarial answer auto-passes only in two cases:
    - it carries a refusal marker (now including "I do not know" and "not verified") and no value matching that exchange's value pattern;
    - or its value is backed by a live-tool call in the same exchange.
  - Everything else is flagged for operator classification, including a dated corpus figure.
  - The `ASOF_MARKERS` auto-pass is removed. **BREAKING** for the scorer verdicts: older runs will rescore with more flags.
- **Markers.**
  - Markers match at word starts, and numeric markers also at word ends, so "41" no longer matches "441".
  - The pin test covers every grounded set, including conflict, with the scorer's boundary rule.
- **Re-baselined battery** (`BATTERY_VERSION` 0.2.0):
  - KB-EX-1 and KB-PA-1 ask for the default split and its per-subnet override.
  - KB-PA-2 matches the corrected subnet-lock destination.
  - KB-EX-6 asks for tempo per subnet.
  - KB-CF-5 markers are re-pinned.
  - KB-UN-3 moves to the historical set with the 2025-02-13 date, and a new unsupported question replaces it.
  - New grounded exchanges cover the WP13 additions: UID immunity, Yuma 3 and liquid alpha, commit-reveal, childkey take, alpha halving, conviction half-lives.
- **Pre-activation retrieval check.**
  - A knowledge test retrieves, from the real corpus, the top 5 units for every grounded battery prompt, and requires each marker group to be satisfied by those units' text.
  - It runs with the retrieval evaluation from `knowledge-retrieval`.
  - The upgrade job runs every suite in its sandbox before ingest and push, and may not edit tests. So a corpus edit that drops a battery fact blocks before the push.
- **Runner matches production.** The battery runs with the production Atlas tool set (all four Atlas MCP servers), and the scorer treats an `atlas-live` call as live evidence.
- **Honesty contract covers mechanisms.**
  - `telegram/docs/voice.md` (canon for `~/.hermes/SOUL.md`): a statement of how the protocol works needs a `knowledge_search` or live-tool result in the session; otherwise it is marked "not verified".
  - The device SOUL.md is updated from canon, with a backup.
- **Corpus polarity lint.** A test with a small checked-in rule file flags a fact unit that states a known-contradictory claim about one operation, for example subnet lock TAO "recycled" or UID registration TAO "burned". Negated phrasing and correction units (which quote wrong claims on purpose) are exempt.
- **Grounding report.** A read-only command reports, for Telegram sessions in a window, how many Bittensor-topic answers made no Atlas knowledge or live call.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `knowledge-base`:
  - The Retrieval benchmark gate's refusal and marker rules.
  - New requirements: markers pinned to the corpus; the pre-activation retrieval check; the corpus polarity lint; the grounding report.
- `agent-voice`: a new requirement that mechanism claims need knowledge or live evidence in the session.
- `live-data` (added 2026-11-05, operator decisions A and 3A): the nine corpus-stated network values are declared reads, in `read-knobs` and in the chain-parameter watch, and a new read-only `live_chain_params` tool serves the watched values to the agent.
- `runtime-upgrade`: the push gate list names the knowledge retrieval checks as part of the test gate.

## Impact

- Code:
  - `knowledge/benchmark/atlas_kb_battery.py` and `atlas_kb_score.py`.
  - New `knowledge/benchmark/atlas_kb_usage.py`.
  - `knowledge/tests`.
  - `hermes/modelval/run_battery.py` (toolset arguments only, if needed).
- Docs:
  - `telegram/docs/voice.md`.
  - `knowledge/README.md` and `knowledge/benchmark/docs/thresholds.md` (refusal rationale).
- Depends on `knowledge-retrieval`: block units, the query builder and the retrieval evaluation. Apply that change first. Both deploy together with the WP13 corpus.
- Pi:
  - SOUL.md update (backup first).
  - Operator `/restart`, so Hermes reloads SOUL.
  - One live battery run afterwards. It costs model calls; approve it separately.
