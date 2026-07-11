# Atlas model validation (ATLAS-HERMES-003, Phase 1)

Validation of the selected model — **Grok (`grok-4.5`) via X OAuth** — as
Atlas actually uses it: through the live Hermes deployment. OpenSpec
change `atlas-phase-1-model-validation`.

**Scope note:** the ATLAS-HERMES-003 *Bittensor retrieval benchmark*
criterion is **deferred to Phase 2 by recorded decision** (retrieval must
exist first). Every report reproduces that deferral; an accepted verdict
here is NOT full ATLAS-HERMES-003 closure.

## The pieces

| file | role |
|---|---|
| [`atlas_modelval_battery.py`](atlas_modelval_battery.py) | the battery: 35 tagged, deterministic exchanges (20 tool-calling, 3 context probes, 6 refusal-to-invent, 6 latency); pure data |
| [`battery.md`](battery.md) | generated human battery document (manual fallback) |
| [`run_battery.py`](run_battery.py) | replays the battery via `hermes -z`, one fresh session per exchange — the ONLY file here that invokes Hermes |
| [`atlas_modelval_score.py`](atlas_modelval_score.py) | read-only scorer: finds exchanges in `state.db` by tag, computes metrics, judges them against the approved threshold sheet |
| [`docs/thresholds.md`](docs/thresholds.md) | operator-approved pass thresholds (unapproved sheet = no acceptance) |
| [`docs/cost-review.md`](docs/cost-review.md) | Q8 subscription cost position (sign-off required) |
| [`docs/privacy-review.md`](docs/privacy-review.md) | PRD §15.7 provider boundary (sign-off + account checks required) |

## Pinned v0.18.2 facts (observed on-device 2026-07-12)

- `hermes -z/--oneshot` exists: single prompt, tools/memory loaded,
  **approvals auto-bypassed** — which is why the runner refuses to start
  without explicit toolset restrictions (`-t`).
- `--usage-file` writes a per-run JSON usage report (kept as evidence).
- `messages.timestamp` is float epoch seconds (sub-ms) → whole-answer
  wall time is honestly measurable; time-to-first-token is not.
- `sessions.input_tokens`/`output_tokens` are populated;
  `estimated_cost_usd` is `0.0` / `cost_status` `unknown` for the OAuth
  provider → token counts are consumption evidence, dollar columns are
  not (the cost validation is `docs/cost-review.md`).

## Acceptance sequence (on the Pi)

```sh
# 0. approve the thresholds (edit docs/thresholds.md, tick [x])
# 1. discover toolset identifiers:
hermes tools list
# 2. run the battery (values from step 1):
python3 hermes/modelval/run_battery.py \
    --toolsets-tc <atlas-test identifier> \
    --toolsets-plain <no-tools identifier>
# 3. score it:
python3 hermes/modelval/atlas_modelval_score.py score
# 4. classify any flagged refusal answers the scorer names:
python3 hermes/modelval/atlas_modelval_score.py score \
    --classify MV-RI-3=refusal ...
# 5. complete + sign off docs/cost-review.md and docs/privacy-review.md
```

Exit codes: `0` accepted · `3` not-accepted (blockers listed) · `4` no
verdict (install record / exceptions file invalid) · `1` fatal. Outputs
(0600, gitignored): `var/modelval/verification-/summary-/audit-<run id>`,
plus the runner's `var/modelval/usage/` and `run-manifest.jsonl`.

## Honesty properties

- The scorer never invokes Hermes and opens the store `mode=ro`; its only
  writes are the reports.
- Unevidenced exchanges block unless explicitly `--attest-exchange`d;
  answers containing numbers in the refusal battery block until the
  operator classifies them (`--classify TAG=fabrication|refusal`); both
  are recorded with operator and timestamp.
- Refusal exchanges that ran with tools enabled are invalid, not scored.
- The report pins the model id and date — changing `model.default` makes
  old acceptance reports visibly stale.
- Exceptions live in gitignored `var/modelval/exceptions.json`
  (`[{"check": ..., "reason": ...}]`), are reproduced in the report, and
  never rewrite a check's status.

## Tests

```sh
cd hermes/modelval/tests && python3 -m unittest discover -v
```

Off-device only (WSL/dev machine), against fixture session stores; the
Pi battery run is the acceptance run.
