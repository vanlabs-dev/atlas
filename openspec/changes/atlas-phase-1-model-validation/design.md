# Design: atlas-phase-1-model-validation

## Context

Grok (`grok-4.5`) runs on the Pi through Hermes v0.18.2 via X OAuth — a
subscription, not a metered API: there is no token bill to read and no
provider-side usage endpoint recorded. All model behavior is observable in
exactly two places: the live session itself (operator's eyes) and the Hermes
session store `state.db` (accepted fact: `messages` rows carry role, content,
`tool_calls`, `tool_name`, `timestamp`; `sessions` rows carry model,
token/cost columns of unknown fidelity for OAuth billing). The repo already
has the pattern this change needs: scripted operator procedure + read-only
evidence tool + attestations for what only a live session shows
(`hermes/memory/`). Two facts are genuinely unknown until implementation:
whether v0.18.2 offers a **headless one-shot invocation** usable for
repeatable batteries, and the **fidelity of token/latency columns** for this
provider — both are resolved by observation early in implementation, never
assumed.

## Goals / Non-Goals

**Goals:**

- One fail-closed verdict over the four testable ATLAS-HERMES-003 criteria
  (tool-calling reliability, context sufficiency, refusal-to-invent,
  latency) plus documented cost/privacy review and replaceability evidence.
- Batteries deterministic enough to re-run after any model/provider change.
- Metrics computed from `state.db` evidence wherever possible; attestation
  only where the store cannot show it.

**Non-Goals:**

- The Bittensor retrieval benchmark (deferred to Phase 2 by recorded
  decision — retrieval must exist first).
- Choosing a fallback model if Grok fails a battery: that decision returns
  to the operator with the evidence.
- A general benchmark framework (PRD §5.6): one battery file, one scorer.
- Statistical rigor beyond the decision need: samples sized to expose gross
  unreliability, not to publish.

## Decisions

1. **Layout mirrors `hermes/memory/`**: `hermes/modelval/` with
   `atlas_modelval_score.py` (read-only scorer), `battery.md` (the scripted
   prompt sets — a procedure doc, one numbered exchange per line, exact
   text), `docs/` (cost review, privacy review, threshold approval sheet),
   `schema/`, `tests/`, `README.md`. Reuses the pinned surfaces
   (`inventory` core via `atlas_hermes_verify`, plus its record/verdict
   helpers) with a `test_import_surface.py`.

2. **The battery is driven through real Hermes sessions, not a bypass API
   client.** ATLAS-HERMES-003 validates the model *as Atlas will use it* —
   through Hermes's prompting, tool wiring, and context handling. A direct
   xAI API client would test a different system (and X OAuth is not a
   general API credential anyway). First implementation task: determine
   whether `hermes` supports a non-interactive one-shot mode; if yes, a thin
   runner script replays the battery mechanically (still through Hermes); if
   no, the operator performs the battery like the memory procedure. Either
   way the session store is the evidence of record.

3. **Each battery exchange carries a machine-findable tag** (e.g.
   `[MV-TC-07]`) typed as part of the prompt. The scorer locates exchanges
   in `state.db` by tag (FTS or LIKE over `messages.content`), pairs each
   user message with the following assistant/tool rows in the same session,
   and computes per-battery metrics. This removes transcript bookkeeping
   from the operator entirely: run the battery, then run the scorer.
   Alternative — operator copies transcripts into files — rejected: error-
   prone, duplicates data the store already holds.

4. **Metrics per battery, from store evidence:**
   - *Tool-calling reliability*: for each `MV-TC-*` exchange, did an
     `atlas_ping` tool call occur and did the final answer reflect its
     result? Success fraction over N (proposed N=20).
   - *Refusal-to-invent*: for each `MV-RI-*` exchange (current price /
     emission / block queries with no live tool available), the scorer
     flags any numeric-claim pattern in the answer; flagged answers are
     shown (redacted) to the operator, who classifies fabrication vs
     legitimate refusal phrasing. Zero fabrications passes (proposed).
   - *Context sufficiency*: `MV-CX-*` recall probes at stepped context
     sizes; pass = correct recall at the size Atlas Phase 2 will actually
     need — the step sizes and the required size are named in the threshold
     sheet, approved by the operator, informed by Hermes's own compression
     settings (observed in config: compression thresholds).
   - *Latency*: per-exchange wall time from `messages.timestamp` deltas
     (request→final answer; time-to-first-token is not observable in the
     store — reported as such, judged against Q8's "a few seconds to first
     token; longer acceptable for tool-heavy answers" via the answer-level
     budget the operator approves).
5. **Token/cost columns are reported, not trusted**: whatever
   `sessions.input_tokens`/`estimated_cost_usd` contain for the OAuth
   provider is recorded as evidence with a fidelity caveat; the *cost
   validation* itself is the documented subscription review (Q8), not
   metering. If the columns are empty or implausible, the report says so.

6. **Thresholds live in a threshold sheet the operator approves before the
   acceptance run** (`docs/thresholds.md`, each line behind an unchecked
   `- [ ] approved` marker, mirroring the hardening-plan pattern). The
   scorer refuses an acceptance verdict against an unapproved sheet.
   Proposed starting values: tool-call success ≥ 19/20; fabrications = 0;
   context recall correct at the approved size; median answer latency
   within the approved budget. PRD §5.5: proposals, not assumptions.

7. **Privacy and cost reviews are dated documents, not code**
   (`docs/privacy-review.md`, `docs/cost-review.md`): xAI/X retention and
   training-use posture for X OAuth Grok access from current official
   sources (labelled web-lead until confirmed authoritative, per PRD §2/
   §5.4), the §15.7 checklist answered, and the subscription cost position.
   The scorer checks these documents exist and carry a review date +
   operator sign-off line; it does not parse their claims.

8. **Replaceability evidence is a config check, not a swap test**: the
   scorer confirms the model selection lives in `config.yaml`
   (`model.default`/`model.provider`/`model.base_url`) and that no Atlas
   repo code references the model name — evidence that swapping is a
   config-only operation. Actually swapping models is out of scope.

9. **Verdict machinery mirrors the accepted verifiers**: same check-status
   vocabulary, exceptions file (`var/modelval/exceptions.json`),
   attestations for operator-performed classification steps, 0600 reports
   (`verification-/summary-/audit-<run id>`) in gitignored `var/modelval/`,
   exit codes 0/3/4/1.

## Risks / Trade-offs

- [No headless mode → battery is operator-driven and tedious] → Battery
  sized for one sitting (~35–40 exchanges total across the four sets);
  tags make scoring automatic; the runner-script path is taken if v0.18.2
  offers one-shot invocation.
- [Store timestamps too coarse for latency] → Resolved by observation in
  task 2; if per-message timestamps prove second-granular that still
  bounds the Q8 judgement; the report states measurement resolution.
- [Refusal-to-invent scoring cannot be fully automated] → Deliberate
  human-in-the-loop: the scorer flags numeric claims, the operator
  classifies, the report records both the flag and the classification —
  same honesty model as attestations.
- [Battery consumes subscription allowance] → Expected exchange count
  stated up front; battery is a fraction of normal daily use; no retry
  storms (each exchange run once; re-runs are operator choices).
- [Grok updates silently change behavior after validation] → The report
  pins model id and date; re-validation triggers are a Phase 2+ operational
  question, noted in the README rather than invented policy here.
- [Privacy review rests partly on provider web pages] → Sources dated and
  labelled; where an authoritative statement cannot be found, the review
  says "unconfirmed" and the §15.7 acceptance decision is the operator's,
  eyes open — never a silent pass.

## Open Questions

- Does Hermes v0.18.2 provide a non-interactive one-shot invocation
  suitable for battery replay? (Resolved by inspection in implementation
  task 2; determines runner vs operator-driven execution.)
- Fidelity of `messages.timestamp` granularity and of token/cost columns
  under the X OAuth provider. (Resolved by observation of an existing
  session; determines how latency is reported.)
- The concrete context sizes Atlas Phase 2 retrieval will need (informs
  the `MV-CX-*` step sizes) — proposed in the threshold sheet from Hermes's
  observed compression settings; operator approves before the run.
