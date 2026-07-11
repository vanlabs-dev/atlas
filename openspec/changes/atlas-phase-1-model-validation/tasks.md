# Tasks: atlas-phase-1-model-validation

## 1. Module scaffolding and contracts

- [x] 1.1 Create `hermes/modelval/` layout (scorer stub, `battery.md`, `docs/`, `schema/`, `tests/`, `README.md`) mirroring `hermes/memory/` conventions
- [x] 1.2 Define the verification-report JSON schema (per-criterion metrics with evidence, flags + operator classifications, threshold results, review sign-off checks, deferral notice, verdict) and pin reused surfaces with `test_import_surface.py`

## 2. Resolve the observation unknowns (before writing checks)

- [x] 2.1 Determine by inspection whether Hermes v0.18.2 offers a non-interactive one-shot invocation suitable for battery replay; record the answer in the module README and choose runner-script vs operator-driven execution *(yes: `hermes -z/--oneshot` + `--usage-file` + `-t`; runner chosen. Caveat found: one-shot AUTO-BYPASSES approvals → runner requires explicit toolset restrictions)*
- [x] 2.2 Observe `messages.timestamp` granularity and token/cost column fidelity for the X OAuth provider from an existing session (read-only); pin what latency reporting can honestly claim *(float epoch seconds, sub-ms → whole-answer wall time measurable, TTFT unobservable and stated so; token counts populated, `estimated_cost_usd` 0.0/`cost_status` unknown → dollar columns caveated)*

## 3. Battery and threshold sheet

- [x] 3.1 Write `battery.md`: tagged, deterministic exchanges for the four sets — `MV-TC-*` tool-calling (proposed N=20 against `atlas_ping`), `MV-CX-*` context recall probes at stepped sizes, `MV-RI-*` refusal-to-invent (current price/emission/block queries), `MV-LA-*` latency exchanges — exact prompts, expected outcomes, total count stated up front *(35 exchanges; battery is data in `atlas_modelval_battery.py`, battery.md generated from it and pinned by test)*
- [x] 3.2 Write `docs/thresholds.md` with proposed pass values (tool-call ≥ 19/20, fabrications = 0, context recall at the approved size, latency budget per Q8) each behind an unchecked `- [ ] approved` marker
- [x] 3.3 Size the `MV-CX-*` steps from Hermes's observed compression settings and state the Phase 2 context assumption they encode *(8k/32k/96k chars ≈ 2k/8k/24k tokens; `compression.threshold: 0.5` observed on-device; 32k-char probe encodes the Phase 2 retrieval-evidence assumption)*

## 4. Cost and privacy reviews

- [x] 4.1 Write `docs/cost-review.md`: subscription cost position for Grok via X OAuth against the Q8 budget, dated, with an operator sign-off line *(tier/price fields left TODO for the operator at sign-off)*
- [x] 4.2 Write `docs/privacy-review.md`: §15.7 boundary for X OAuth Grok (retention, training use, telemetry) from current official sources — each source dated, web-derived claims labelled, unconfirmed items stated as unconfirmed — with an operator sign-off line *(training-use claims CONFLICT across sources; recorded as Conflicting with the account-setting check as the resolution action)*

## 5. Scorer (read-only)

- [x] 5.1 Tag-based exchange location in `state.db` (strictly `mode=ro`), pairing each battery prompt with its assistant/tool rows; unevidenced exchanges → attestation fallback, never silent scoring
- [x] 5.2 Per-criterion metric computation: tool-call success fraction, context recall correctness, latency from timestamp deltas (resolution reported; TTFT stated as unobservable), token/cost columns reported with fidelity caveat
- [x] 5.3 Refusal-to-invent flagging (numeric/value-shaped claims) with redacted presentation for operator classification via CLI input; both flag and classification recorded *(flag = any digit in the final answer; `--classify TAG=fabrication|refusal`)*
- [x] 5.4 Threshold-sheet gate (unapproved sheet → no acceptance verdict), review sign-off checks, replaceability evidence (config keys hold the model id; no repo code references it), pinned model id + date, deferral notice in the report
- [x] 5.5 Fail-closed verdict, exceptions file (`var/modelval/exceptions.json`), 0600 reports (`verification-/summary-/audit-<run id>`) into gitignored `var/modelval/`, exit codes 0/3/4/1

## 6. Off-device verification (WSL)

- [x] 6.1 Unit tests per metric with fixture session stores (tagged exchanges: green runs, missing tool calls, fabricated values, missing exchanges) and fixture threshold sheets (approved/unapproved)
- [x] 6.2 Full-run integration test: green fixture run accepted; each single blocker (metric fail, unapproved threshold, unsigned review, unevidenced exchange) yields not-accepted naming it; read-only surface test (import allowlist, `mode=ro`, no direct writable opens) *(46 tests green on WSL; battery module pinned pure; runner is the only Hermes-invoking file)*

## 7. On-device acceptance (operator + scorer on the Pi)

- [ ] 7.1 Operator approves the threshold sheet (and adjusts values first where wanted)
- [ ] 7.2 Run the battery through live Hermes (runner script if 2.1 found one-shot support, otherwise operator-driven per `battery.md`) *(runner it is: discover toolset identifiers with `hermes tools list`, then `run_battery.py --toolsets-tc ... --toolsets-plain ...`)*
- [ ] 7.3 Run the scorer, perform the refusal-to-invent classifications, and re-run after fixing any evidence gaps
- [ ] 7.4 Operator signs off the cost and privacy reviews *(cost review needs tier/price filled in; privacy review needs the policy read + the account training-toggle checked and recorded)*
- [ ] 7.5 Record the verdict, run id, pinned model id, and the retrieval-benchmark deferral in `docs/decisions.md`; update root `README.md`; archive the change
