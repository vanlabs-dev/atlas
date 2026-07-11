# Tasks: atlas-phase-1-model-validation

## 1. Module scaffolding and contracts

- [ ] 1.1 Create `hermes/modelval/` layout (scorer stub, `battery.md`, `docs/`, `schema/`, `tests/`, `README.md`) mirroring `hermes/memory/` conventions
- [ ] 1.2 Define the verification-report JSON schema (per-criterion metrics with evidence, flags + operator classifications, threshold results, review sign-off checks, deferral notice, verdict) and pin reused surfaces with `test_import_surface.py`

## 2. Resolve the observation unknowns (before writing checks)

- [ ] 2.1 Determine by inspection whether Hermes v0.18.2 offers a non-interactive one-shot invocation suitable for battery replay; record the answer in the module README and choose runner-script vs operator-driven execution
- [ ] 2.2 Observe `messages.timestamp` granularity and token/cost column fidelity for the X OAuth provider from an existing session (read-only); pin what latency reporting can honestly claim

## 3. Battery and threshold sheet

- [ ] 3.1 Write `battery.md`: tagged, deterministic exchanges for the four sets — `MV-TC-*` tool-calling (proposed N=20 against `atlas_ping`), `MV-CX-*` context recall probes at stepped sizes, `MV-RI-*` refusal-to-invent (current price/emission/block queries), `MV-LA-*` latency exchanges — exact prompts, expected outcomes, total count stated up front
- [ ] 3.2 Write `docs/thresholds.md` with proposed pass values (tool-call ≥ 19/20, fabrications = 0, context recall at the approved size, latency budget per Q8) each behind an unchecked `- [ ] approved` marker
- [ ] 3.3 Size the `MV-CX-*` steps from Hermes's observed compression settings and state the Phase 2 context assumption they encode

## 4. Cost and privacy reviews

- [ ] 4.1 Write `docs/cost-review.md`: subscription cost position for Grok via X OAuth against the Q8 budget, dated, with an operator sign-off line
- [ ] 4.2 Write `docs/privacy-review.md`: §15.7 boundary for X OAuth Grok (retention, training use, telemetry) from current official sources — each source dated, web-derived claims labelled, unconfirmed items stated as unconfirmed — with an operator sign-off line

## 5. Scorer (read-only)

- [ ] 5.1 Tag-based exchange location in `state.db` (strictly `mode=ro`), pairing each battery prompt with its assistant/tool rows; unevidenced exchanges → attestation fallback, never silent scoring
- [ ] 5.2 Per-criterion metric computation: tool-call success fraction, context recall correctness, latency from timestamp deltas (resolution reported; TTFT stated as unobservable), token/cost columns reported with fidelity caveat
- [ ] 5.3 Refusal-to-invent flagging (numeric/value-shaped claims) with redacted presentation for operator classification via CLI input; both flag and classification recorded
- [ ] 5.4 Threshold-sheet gate (unapproved sheet → no acceptance verdict), review sign-off checks, replaceability evidence (config keys hold the model id; no repo code references it), pinned model id + date, deferral notice in the report
- [ ] 5.5 Fail-closed verdict, exceptions file (`var/modelval/exceptions.json`), 0600 reports (`verification-/summary-/audit-<run id>`) into gitignored `var/modelval/`, exit codes 0/3/4/1

## 6. Off-device verification (WSL)

- [ ] 6.1 Unit tests per metric with fixture session stores (tagged exchanges: green runs, missing tool calls, fabricated values, missing exchanges) and fixture threshold sheets (approved/unapproved)
- [ ] 6.2 Full-run integration test: green fixture run accepted; each single blocker (metric fail, unapproved threshold, unsigned review, unevidenced exchange) yields not-accepted naming it; read-only surface test (import allowlist, `mode=ro`, no direct writable opens)

## 7. On-device acceptance (operator + scorer on the Pi)

- [ ] 7.1 Operator approves the threshold sheet (and adjusts values first where wanted)
- [ ] 7.2 Run the battery through live Hermes (runner script if 2.1 found one-shot support, otherwise operator-driven per `battery.md`)
- [ ] 7.3 Run the scorer, perform the refusal-to-invent classifications, and re-run after fixing any evidence gaps
- [ ] 7.4 Operator signs off the cost and privacy reviews
- [ ] 7.5 Record the verdict, run id, pinned model id, and the retrieval-benchmark deferral in `docs/decisions.md`; update root `README.md`; archive the change
