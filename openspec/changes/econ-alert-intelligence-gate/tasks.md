## 1. Verdict store

- [x] 1.1 Add an `econ_verdicts` table to the fleet-store schema init: columns for content hash (PK), netuid, range_id, prev_sha, new_sha, matched_files, significance, direction, what_changed, why_it_matters, evidence, outcome (`alert`/`digest`/`drop`/`unjudged`), partial_view flag, model id, created_at.
- [x] 1.2 Implement `verdict_lookup(content_hash)` and `verdict_record(...)` helpers; content hash = stable hash of `(prev_sha, new_sha, sorted matched econ files)`.
- [x] 1.3 Unit tests: hash stability across file-order permutations, lookup hit/miss, record round-trip including drops and unjudged rows.

## 2. Judge via Hermes one-shot CLI (injectable)

- [x] 2.1 Add a judge config block to fleet signals config: `hermes` invocation settings (binary path/discovery, toolset spec = none), `timeout_seconds`, `max_calls_per_run`, `max_calls_per_day`, `max_diff_bytes`, `high_stakes_paths`, and a gate `enabled` flag (default off). No provider/model/key fields — model is selected by Hermes config.
- [x] 2.2 Implement a Hermes one-shot invoker that shells out to the `hermes` CLI (`-z <prompt>`, no toolsets, no memory write), mirroring `hermes/modelval/run_battery.py:86-92` incl. hermes discovery; reuse the X OAuth session; no API key or model id in fleet code.
- [x] 2.3 Build the judge prompt: untrusted-diff fence, instruction to emit only a JSON object with the fixed schema (`what_changed`, `why_it_matters`, `significance`, `direction`, `evidence`).
- [x] 2.4 Implement `default_econ_judge(diff, files, context)` that invokes Hermes and returns a validated verdict; parse JSON from stdout, strict schema validation, retry-once on malformed, then `unjudged`; empty `evidence` coerces `significance` to `none`.
- [x] 2.5 Route all invocation error text through the existing redaction scrubber before it can be stored or displayed.
- [x] 2.6 Unit tests with a stub judge (no real subprocess): schema-valid parse, malformed→retry→unjudged, empty-evidence coercion, injection-directive-in-diff has no effect on returned routing, locked-down invocation (no toolsets/memory) asserted, errors redacted.

## 3. Gate in `process_range`

- [x] 3.1 At the econ chokepoint (`fleet/atlas_fleet_signals.py:~794`), compute matched econ files and the content hash; on cache hit reuse the stored verdict with no model call.
- [x] 3.2 On cache miss, fetch the bounded aggregate diff for matched files from the local clone via read-only git (reuse `_diff_added_lines`/`_run_git`); truncate to `max_diff_bytes` and set `partial_view` when exceeded; missing clone/diff → `unjudged`.
- [x] 3.3 Enforce per-run and per-day budget and per-call timeout; over-budget or timeout → `unjudged`; never raise into the reconcile pass.
- [x] 3.4 Call the injected judge, persist the verdict, then route: `high`/`med` → instant event; `low` → digest line; `none` → record-and-drop.
- [x] 3.5 Apply the high-stakes path floor: matched `mechanism`/`set_weights`/`emission` paths never route below digest, including on `none`/`unjudged`.
- [x] 3.6 Make cooldown significance-aware: `high` breaks through and pages; `med`/`low`/`unjudged` respect the window and demote to digest.
- [x] 3.7 Extend the queued payload with verdict fields so the renderer needs no store access at render time.
- [x] 3.8 Thread the judge as an injected dependency (mirror `default_price_fetcher`) so tests pass a stub.
- [x] 3.9 Tests: material→page, cosmetic→drop+recorded, high-stakes-none→digest, high-breaks-cooldown, med-within-cooldown→digest, cache-hit skips model call, budget/timeout→unjudged, idempotent re-run.

## 4. Card rendering

- [x] 4.1 Rewrite `_build_econ_event` (`telegram/atlas_telegram.py:~1215`) to lead with `what_changed` and `why_it_matters`, then a significance+direction line, then a single compact footer (SHA range · commit count · files · entry price).
- [x] 4.2 Drop the standing repositories-not-chain disclaimer for the econ class; render an explicit `unjudged` marker when the verdict is absent.
- [x] 4.3 HTML-escape and length-bound all verdict free-text; keep the 400-fallback path.
- [x] 4.4 Tests: meaning-first layout with a material verdict, escaped/inert verdict text, unjudged marker, dedup-by-range-id preserved, HTML-400 fallback still works.

## 5. Observability

- [x] 5.1 Extend `status` to report gate counters: candidates, alerted, digested, dropped, unjudged, and model calls vs. per-day budget.
- [x] 5.2 Test: `status` surfaces the counters from recorded verdict rows.

## 6. Integration & docs

- [x] 6.1 End-to-end test with a stub judge from range detection through rendered card for each outcome (alert/digest/drop/unjudged), using fixture clones/diffs — no subprocess, no network.
- [x] 6.2 Verify model-validation's no-hard-coded-model-id scan still passes and that no API-key credential is introduced in fleet code.
- [x] 6.3 Document the judge config block and the Hermes-CLI dependency (reuses the X OAuth subscription — no new secret); note the extract unit must resolve `hermes` with a healthy OAuth session, gate defaults off, forward-only deploy.
- [x] 6.4 Update README/specs sync notes as per project convention; run `openspec validate --change econ-alert-intelligence-gate`.
