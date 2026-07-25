## Why

Incentive-code (`econ-code`) fleet alerts fire on a **file-path substring match** and never read the diff, so every card says the same thing — `incentive-code change` plus git mechanics (SHA→SHA, file list, commit count) — with no notion of what actually changed or whether it matters. The operator gets many such alerts and cannot tell a consensus rewrite from a comment tweak; the alerts are too frequent to act on and too shallow to be worth reading. The data to do better (the diff, the clone) is already local; what is missing is a judgment layer between "a watched path moved" and "page the operator."

## What Changes

- Insert an **intelligence-and-materiality gate** between econ-path detection and alert emission: read the actual diff from the local clone, judge it with **Grok via the Hermes one-shot CLI** — reusing the ratified X OAuth subscription (no new secret, no metered key) — and decide alert vs digest vs drop.
- The judge returns a **structured, evidence-grounded verdict** — `what_changed`, `why_it_matters`, `significance ∈ {high,med,low,none}`, `direction ∈ {emissions_up, emissions_down, reshuffle, neutral, unknown}`, plus the changed lines/symbols the verdict rests on. Empty evidence forces `none`.
- **Gate outcomes:** `high`/`med` → full alert led by the interpretation · `low` → existing digest bucket · `none`/cosmetic → dropped (but logged).
- Diff content is treated as **untrusted third-party input** — structurally fenced from instructions in the prompt, fixed output schema, so a subnet cannot steer Atlas's alerts (or the operator's trades) via a crafted comment.
- **High-stakes path floor:** changes touching `mechanism` / `set_weights` / `emission` paths can never be dropped below a digest, backstopping model misjudgment on the most dangerous files.
- **Significance-aware cooldown:** a `high` verdict breaks through the 24h per-netuid cooldown; `med`/`low` respect it. Fixes today's inversion where a cosmetic change alerts first and a later material one is demoted to an "in cooldown" trailer.
- **Verdict store** (`econ_verdicts`), keyed by a content hash of `(prev_sha, new_sha, sorted econ files)`: gives idempotent re-runs, a verdict cache (no re-calls), and an audit log of every drop so false negatives are reviewable.
- **Budget + timeout + fail-soft:** per-run and per-day model-call caps (mirrors the TaoStats self-cap posture); over-budget, timed-out, or malformed-response candidates ship as `· unjudged` rather than block the extract or vanish.
- **Card redesign:** the econ card leads with `what_changed` / `why_it_matters` / significance + direction as the visible head; SHA, files, commit count, entry price, and evidence tuck into an expandable blockquote of labeled single-fact lines (blank-line groups) so it reads as a glanceable card, not a wall of text; the boilerplate `source:` disclaimer is dropped. Model free-text is HTML-escaped.
- **Observability:** `status` reports gate stats (candidates / alerted / digested / dropped / unjudged / budget used).
- Model access **reuses Hermes** — the judge invokes the local `hermes` one-shot CLI (locked down: no toolsets, no memory write), so Grok is selected by Hermes's own config (`model.default`) and no model id, provider endpoint, or credential is introduced in fleet code. Honors the replaceability rule enforced by model-validation and the Q7 "OAuth, not a metered key" decision.

Scope is limited to the `econ-code` class. Narrative, watchlist, and model-id-cluster signals are untouched.

## Capabilities

### New Capabilities
- `econ-alert-intelligence`: reads the diff for an econ-path change candidate, obtains an evidence-grounded significance verdict from Grok via a locked-down Hermes one-shot invocation under an untrusted-input contract, persists and caches verdicts in a store keyed by change content, and enforces budget / timeout / fail-soft behavior. Owns the materiality decision (alert / digest / drop) and the high-stakes path floor.

### Modified Capabilities
- `fleet-signals`: the econ-code requirement changes from "detected by path and alerted per range" to "detected by path, then **gated by verdict** before emission"; cooldown becomes significance-aware; dropped candidates are recorded, not silently discarded.
- `telegram-integration`: the econ card renders the verdict (meaning-first layout, escaped model text, `unjudged` marker) instead of the label-plus-mechanics card.

## Impact

- **Code:** `fleet/atlas_fleet_signals.py` (`process_range` chokepoint ~`:794`, new verdict step, store schema, `status`); a new judge module that invokes the `hermes` CLI (injectable, following the `default_price_fetcher` pattern; the subprocess shape mirrors `hermes/modelval/run_battery.py`); `telegram/atlas_telegram.py` `_build_econ_event` renderer and payload fields.
- **Data:** new `econ_verdicts` table in the fleet store (`var/fleet/fleet.db`). No change to reconcile store schema.
- **Config / auth:** new judge config block (hermes invocation settings, caps, timeout, diff bound, high-stakes patterns, `enabled` flag). Auth **reuses the existing Hermes X OAuth subscription** — **no new secret, no metered key** — preserving the accepted Q7 cost/privacy posture. Model errors routed through existing redaction. Introduces the pipeline's **first model call**, invoked locally through Hermes (which reaches Grok).
- **Dependencies:** the `hermes` CLI present on the box running the extract (already installed on the Pi); no new runtime service, no new credential, no new HTTP client.
- **Ops:** the hourly repo/extract run may take longer when candidates exist — each is a Hermes subprocess, bounded by budget + timeout; no schema migration needed on the reconcile side; deployed forward-only (no backfill re-judging of historical ranges).
