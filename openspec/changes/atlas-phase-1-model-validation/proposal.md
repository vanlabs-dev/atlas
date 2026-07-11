# Proposal: atlas-phase-1-model-validation

Governing documents: [prd.md](../../../prd.md) (§12.2 ATLAS-HERMES-003, §15.7
privacy) and [docs/decisions.md](../../../docs/decisions.md): Grok (xAI) via
X OAuth is the first candidate (Q7 — subscription auth, not a metered API key),
~$20/month at interactive latency (Q8), hosted models allowed (Q9). The Hermes
baseline and memory/session-recall are accepted; Grok chat + tool calls are
*working* but explicitly **not validated** — the decision log carries this as a
standing pre-production gate.

## Why

ATLAS-HERMES-003 forbids production use of an unvalidated model: tool-calling
reliability, context sufficiency, cost, latency, privacy implications, and
refusal to invent unavailable live data must each be evidenced, and today none
of them are — acceptance rested on a single successful `atlas_ping` call. The
refusal-to-invent criterion is also the behavioral foundation of the entire
fail-closed live-data design (PRD §5.2): if the model fabricates "current"
values in plain chat, no adapter discipline downstream can fully compensate.
This gate must close before Phase 2 corpus work builds on the model.

## What Changes

- **A scripted validation battery** (`hermes/modelval/`, following the repo's
  procedure + verifier pattern): deterministic prompt sets the operator (or a
  headless Hermes invocation, if v0.18.2 supports one — an unknown to resolve
  early) runs through the live Grok-backed Hermes:
  - **tool-calling reliability** — N repetitions of scripted tool-call tasks
    against the inert `atlas_ping` MCP tool; success rate measured;
  - **context window sufficiency** — recall probes at increasing context sizes
    within what Hermes actually sends;
  - **refusal to invent unavailable live data** — prompts requesting current
    Bittensor prices/emissions/block data while no live tool exists; the only
    passing behavior is an explicit "cannot verify / unavailable", never a
    number;
  - **latency** — per-exchange response latency derived from evidence, judged
    against the Q8 expectation.
- **A read-only scorer** (`atlas_modelval_score.py`) that computes the metrics
  from the session store (`state.db`, opened `mode=ro` — message rows,
  tool-call records, and timestamps are the evidence), writes redacted 0600
  reports into gitignored `var/modelval/`, and fails closed: every metric
  either meets its operator-approved threshold, carries a documented
  exception, or blocks. Batteries the store cannot evidence fall back to
  operator attestation, recorded as such.
- **A documented cost and privacy review** (`hermes/modelval/docs/`): the
  operating-cost reality of subscription-auth Grok (no per-token metering to
  observe; the subscription is the cost, per Q8) and the §15.7 privacy
  boundary — xAI/X retention and training-use posture for X OAuth Grok
  access, from current official sources, dated and labelled per PRD §2 (web
  material stays a lead until confirmed against an authoritative page).
- **Model-replaceability evidence**: confirm the model is swappable through
  `config.yaml` (`model.default` / `model.provider` / `model.base_url`
  observed on-device) without touching any Atlas data contract.
- **A recorded deferral**: the *Bittensor retrieval benchmark* criterion of
  ATLAS-HERMES-003 cannot run before Phase 2 retrieval exists; this change
  records that deferral explicitly in `docs/decisions.md` as a Phase 2
  acceptance gate rather than silently dropping it.
- **Thresholds are operator decisions, not code defaults**: the battery ships
  with proposed pass thresholds (e.g. tool-call success rate, zero
  fabrications, latency budget) behind explicit approval markers; nothing is
  accepted against an unapproved threshold (PRD §5.5).
- Explicitly out of scope: selecting or switching to a different
  model/provider (this validates the Q7 candidate; a failed validation
  returns the choice to the operator); the Bittensor retrieval benchmark
  itself; any TaoStats/TaoSwap integration; any device mutation beyond
  gitignored `var/` outputs; Telegram; Phase 2 corpus work.

## Capabilities

### New Capabilities

- `model-validation`: ATLAS-HERMES-003 validation of the selected
  provider/model through the live Hermes deployment — scripted batteries for
  tool-calling reliability, context sufficiency, refusal-to-invent, and
  latency; evidence-based scoring from the session store; documented cost and
  privacy review; model-replaceability evidence; operator-approved thresholds
  and a fail-closed acceptance verdict, with the retrieval benchmark
  explicitly deferred to Phase 2.

### Modified Capabilities

None. (`hermes-baseline` and `memory-session-recall` are preconditions and
unchanged; `atlas_ping` is used as the tool-call target exactly as accepted.)

## Impact

- **Device**: no mutation by repo code. Running the battery necessarily
  creates Hermes sessions (operator-driven, like the memory procedure); the
  scorer only reads. Outputs are 0600 reports in gitignored `var/modelval/`.
- **Cost**: battery runs consume the Grok subscription's usage allowance —
  the battery is sized to stay well inside a normal day's interactive use,
  and the design must state the expected exchange count up front.
- **Repo**: new `hermes/modelval/` module beside `hermes/memory/`, reusing
  the pinned inventory/baseline machinery (probe/redaction/schema, record
  loading, verdict computation).
- **Privilege**: none. Same posture as the other verifiers.
- **Testing**: off-device (WSL) against fixture session stores and captured
  transcripts; the Pi battery run is the acceptance run.
- **Downstream**: closes the last Phase 1 gate before Phase 2 corpus intake;
  the deferred retrieval benchmark becomes a named Phase 2 acceptance
  criterion; privacy review satisfies the §15.7 pre-production requirement
  for the model boundary.
