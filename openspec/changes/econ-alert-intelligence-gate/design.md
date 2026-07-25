## Context

`econ-code` fleet alerts are generated in `fleet/atlas_fleet_signals.py`. Detection is pure path matching: `is_econ_path` (`:296`) tests whether a changed path contains any token in `econ_paths` (`reward`/`incentive`/`scoring`/`emission`/`set_weights`/`mechanism`, `:202`), and `process_range` (`:793-821`) queues an instant `econ-code` event for any range with a non-empty econ-file set. The diff is never read; there is no significance notion; the only throttle is a 24 h per-netuid cooldown that demotes repeats to a digest line. Rendering is in `telegram/atlas_telegram.py` `_build_econ_event` (`:1215-1241`), which prints only the queued payload (`netuid`, SHAs, `files[:12]`, `commit_count`) plus a read-only entry-price lookup. No LLM call exists anywhere in the pipeline today.

The single chokepoint that already holds `clone_dir`, `prev_sha`, `new_sha`, and the matched econ files is `process_range:794`. The diff is one read-only git call from the local blobless clone away (`_diff_added_lines`, `:666-687`). This change inserts a judgment step at that chokepoint and threads the verdict into the render payload.

Relevant constraints: model selection must be config-only — model-validation (`hermes/modelval/atlas_modelval_score.py:737`) fails the build if a model id is hard-coded in code. The fleet store already has redaction and a concurrent-reader contract. Extraction runs inline after reconcile and must never turn a failure into a reconcile process error (`fleet-signals` spec, "Extraction is per-range fail-closed and inline on reconcile").

## Goals / Non-Goals

**Goals:**
- Replace "a scoring path moved" with "here is what changed, why it matters, and how significant" — driven by reading the actual diff.
- Suppress cosmetic/noise econ changes before they page; surface only material ones.
- Never silently lose a real change (fail-soft, high-stakes floor, auditable drops).
- Keep the judgment robust against untrusted, possibly adversarial diff content.
- Stay within Atlas conventions: config-driven model, env-only secret, off-device-testable, fail-closed extraction, house-style rendering.

**Non-Goals:**
- No change to narrative-cluster, watchlist, or model-id signal classes.
- No per-commit judgment (range-aggregate only), no backfill re-judging of historical ranges.
- No new long-running service; the judge runs inline within the existing extract pass.
- No on-device/local model (Pi 5 has no GPU); the judge is a hosted call.

## Decisions

**D1 — Insert the gate inline at the `process_range` chokepoint, not as a separate async worker.**
At `:794-821` all inputs are already in hand and the verdict flows straight into the existing payload/render path with no new plumbing. A separate enrichment worker (a `pending_judgment` queue drained by its own unit) was considered and rejected as more infrastructure than the volume warrants; budget caps + timeout + the verdict cache bound the inline cost adequately. If observed volume ever makes the inline call dominate extract latency, the verdict store already provides the seam to move drainage to a later step without changing the contract.

**D2 — A content-hash-keyed `econ_verdicts` table is the linchpin.**
Key = hash of `(prev_sha, new_sha, sorted matched econ files)`. This single structure delivers three things at once: idempotent re-runs (extract re-processing a range reuses the verdict), a call cache (no duplicate model spend), and an audit log of drops and `unjudged` outcomes so false negatives are reviewable. Keying on `range_id` was rejected — range ids are not guaranteed stable across re-chunking; content is.

**D3 — Evidence-grounded, schema-fixed verdict; empty evidence ⇒ `none`.**
The model must cite the changed lines/symbols its judgment rests on. This both improves quality and yields a verifiable card footer. Because trade-relevant text must not be confidently fabricated, an ungrounded verdict cannot claim significance. Temperature 0, strict JSON validation, retry-once, then `unjudged`.

**D4 — Diff is untrusted input under an injection contract.**
Diff hunks are fenced from instructions in the prompt; the model is bound to the fixed output schema. Subnet-authored text (comments, strings) is data and cannot alter significance, direction, or routing. Verdict text is likewise data at render time — HTML-escaped, never interpreted. This directly reflects the instruction-source boundary: third-party repo content feeding a model that drives the operator's alerts is an attack surface.

**D5 — Two independent signals decide routing: the model verdict and a cheap high-stakes path floor.**
Verdict routes `high`/`med` → alert, `low` → digest, `none` → drop. Independently, a matched path under `mechanism`/`set_weights`/`emission` cannot route below digest even on a `none`/`unjudged` verdict. The floor is the deterministic backstop for model error on exactly the files where a miss is most costly (consensus, weight-setting, emissions). It reuses the existing path vocabulary — no new heuristic classifier (rejected: rebuilding a path-heuristic filter is the very brittleness this change removes).

**D6 — Significance-aware cooldown.**
`high` breaks through the 24 h per-netuid cooldown and pages; `med`/`low` respect it and demote to digest. Fixes the current inversion where a cosmetic change consumes the cooldown slot and a later material change is hidden as an "in cooldown" trailer.

**D7 — Reuse the Hermes X OAuth subscription via a locked-down one-shot CLI call, not a metered key.**
The judge shells out to the local `hermes` CLI in one-shot mode (`-z <prompt>`, no toolsets, no memory write) — the same subprocess pattern the model-validation battery already uses (`hermes/modelval/run_battery.py:86-92`) — and parses a JSON verdict from stdout. This reuses the ratified Q7 auth (`docs/decisions.md:22`, "Grok via X OAuth, not a metered API key") so there is **no new secret and no metered billing**, and it keeps the accepted cost/privacy reviews valid (a metered `xai-…` key would invalidate them — `hermes/modelval/docs/cost-review.md:42`). A direct OpenAI-compatible HTTP client with a dedicated `xai-…` key was considered and rejected on that basis. The judge is a function injected into `process_range` exactly like `default_price_fetcher` (`:1011`), so tests pass a stub and CI never spawns Hermes or touches the network. The model is named only in Hermes config (`model.default`), satisfying the replaceability check with nothing to hard-code in fleet code. Trade-offs accepted: a subprocess per candidate (heavier than an HTTP call, fine at econ-candidate volume) and JSON produced by prompting rather than a native JSON mode (handled by strict parse + retry-once → `unjudged`).

**D8 — Budget + timeout + fail-soft.**
Per-call subprocess timeout, per-run and per-day call caps (mirrors the TaoStats self-cap posture already in the project — protects the subscription and bounds extract latency). Exhausting budget or hitting a timeout kills the subprocess and emits `unjudged` (subject to the high-stakes floor), never blocks the pass, never counts as a reconcile error. Invocation error text is redacted through the existing scrubber before storage/display.

**D9 — Card leads with meaning; detail collapses into an expandable blockquote.**
`_build_econ_event` renders `what_changed`, `why_it_matters`, a blank-line separator, then a significance+direction line as the always-visible head; SHA range, commit count, files, entry price, and evidence go into an expandable blockquote of labeled single-fact lines (blank-line-separated groups) — the same display method the subtensor repo breakdown uses (`_breakdown_lines`), so the card is scannable at a glance instead of a run-on footer. The standing "repositories, not chain" disclaimer is dropped for this class. `unjudged` candidates show an explicit marker. All model text is escaped and length-bounded per the existing untrusted-render rule.

## Risks / Trade-offs

- **Adversarial diff manipulates the verdict** → D4 injection contract (fenced prompt, fixed schema, data-only rendering) plus D5 deterministic high-stakes floor that the model cannot talk its way under.
- **Model false-negative drops a real change** → D5 path floor for the dangerous files; D2 audit log makes all `none`/`unjudged` drops reviewable so calibration can catch misses; forward-only deploy lets the operator watch the drop log before trusting the gate.
- **Model latency/cost inflates the hourly extract** → D8 timeout + per-run/per-day caps + D2 cache; over-budget degrades to `unjudged` rather than stalling. Range-aggregate (not per-commit) judgment bounds tokens; oversized diffs are truncated and flagged.
- **Nondeterministic verdicts flip alert↔drop across re-runs** → temperature 0 + D2 content-hash cache means a given change is judged once and reused.
- **Model/Hermes outage** → fail-soft to `unjudged` cards (marked), so the operator still learns a watched path moved; no missed detection, only missing interpretation.
- **Multi-commit range collapses distinct edits** → accepted trade-off for cost; the partial-view flag and evidence citations keep the card honest about scope.
- **Untrusted diff reaches the Hermes agent** → invoked locked down (no toolsets, no memory write), so injected diff text cannot trigger tools or persist; redaction on all error paths; no credential is handled by fleet code to leak in the first place.
- **Subprocess overhead inflates extract latency** → per-call timeout + per-run/day caps + verdict cache; over-budget degrades to `unjudged`.

## Migration Plan

1. Add the `econ_verdicts` table to the fleet store (`var/fleet/fleet.db`) via the module's existing schema-init path; additive, no reconcile-store change.
2. Add the judge config block (hermes invocation settings, caps, timeout, size bound, high-stakes patterns) with the gate defaulting **off** until configured; ship the Hermes-CLI judge + prompt behind the injection seam.
3. Confirm the `hermes` CLI is resolvable from the extract's environment (the systemd unit that runs it) and that its X OAuth session is healthy — reuse the modelval hermes-discovery approach; no credential is added to the repo or the unit.
4. Enable the gate; run forward-only (no historical re-judging). Watch `status` gate counters and the drop-audit rows for the first days to calibrate the significance threshold and high-stakes vocabulary before trusting drops.
5. Rollback: disable the gate in config — detection reverts to emitting every candidate as it does today; the table and judge remain dormant and harmless.

## Open Questions

- Exact significance-threshold calibration (where `med`/`low` split) — to be tuned against the drop-audit log after a live observation window, mirroring how fleet-signals calibrated `k`/window/novelty.
- Whether to give the model the changed file's bounded full new-content for grounding vs. hunks only — start with size-capped hunks; revisit if verdict quality on large files proves weak.
- Per-day budget number — set conservatively at first from observed candidate volume, adjust once real fleet cadence is measured.
