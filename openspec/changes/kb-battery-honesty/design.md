# Design

## Context

See proposal.md (Why) for the motivation. How the pieces fit today:

- **Battery** (`knowledge/benchmark/atlas_kb_battery.py`): pure data plus marker functions.
- **Runner** (`hermes/modelval/run_battery.py`): sends each prompt through `hermes -z` in a fresh session.
- **Scorer** (`atlas_kb_score.py`): reads the Hermes session store read-only, uses the modelval machinery, and issues a verdict against the operator-approved threshold sheet.
- **Upgrade job test gate** (`upgrade/atlas_upgrade.py` `step_test`): runs every `*/tests` suite inside bwrap before `ingest` and `push`. Its scope gate forbids edits outside the corpus, supersession markers and `docs/decisions.md`.
- **SOUL canon**: `telegram/docs/voice.md`. The operator applies it to `~/.hermes/SOUL.md`, and the `agent-voice` spec requires a read-only match check.

## Goals / Non-Goals

**Goals:**
- Every refusal-set rule can fail on a fabricated value.
- Every grounded marker is satisfiable from the corpus. A test proves it.
- A corpus edit that removes a battery fact fails before the push, with no model call.

**Non-Goals:**
- No model-graded scoring and no LLM judge. Scoring stays deterministic plus operator classification.
- No automated live battery in the upgrade job. A live run needs Hermes, costs model calls, and cannot target a staged run.

## Decisions

**1. Per-exchange value patterns for refusal sets.**
- Each unsupported or adversarial exchange carries a `value_pattern`: a regex for the asked-for value. Examples: a USD amount for price, a 7+ digit or comma-grouped integer for a block number, an integer near "miners" for counts.
- Auto-pass happens in exactly two cases:
  - (a) a refusal marker is present and `value_pattern` does not match;
  - (b) `value_pattern` matches and the exchange has a tool row from `atlas-live` (or `atlas-fleet` for fleet counts).
- Everything else goes to operator classification, as today.

Alternative considered: auto-fail every value. Rejected because a sourced live value is the correct production answer.

**2. Marker boundaries.**
- An alternate matches at a word start: `(?<![a-z0-9])`.
- An alternate ending in a digit or `%` also needs a word end.
- Stems such as `recycl` and `proportional` keep prefix matching.

**3. The marker pin test** asserts, for every grounded exchange, that each marker group has at least one alternate found in the corpus text, using the same boundary rule. It runs in `knowledge/tests`.

**4. The pre-activation retrieval check is a knowledge test, not job code.**
- It ingests the real corpus into a temporary store, activates the run, and calls the server's search for each grounded prompt with `max_results` 5.
- It requires `markers_match` over the concatenated result contents.
- Prompts are the user wording, so this also tests the query builder.

Why a test and not a job step:
- the job already runs every suite on the edited worktree before ingest and push;
- the job cannot edit tests, so the model cannot weaken the check;
- a manual re-sync runs the same suites (`SOURCES.md` step 7).

Trade-off: a legitimate corpus change that retires a battery fact blocks the job until the operator re-baselines the battery. That is the intended per-spec re-baseline (audit A8).

**5. Runner toolset.**
- Run with the production Atlas set, so the battery measures what Telegram users get.
- The scorer's tool-call evidence for grounded sets stays "a knowledge tool was called".
- For refusal sets, tool rows decide case (b).
- The runner's `--toolsets-*` arguments are documented as advisory, because Hermes adds enabled MCP servers anyway (WP10 trace).

**6. Mechanism-claim honesty.**
- An `agent-voice` requirement next to the numeric one; the numeric requirement keeps its name.
- Voice canon text: "No tool evidence, no mechanism claim. A statement of how the protocol works (a rule, a default, a limit, a date, which call does what) needs a `knowledge_search` or live-tool result in this session. Otherwise say it is not verified."
- The KB tool description already says "USE THIS FIRST".

**7. Grounding report.**
- `atlas_kb_usage.py report --days N` opens `~/.hermes/state.db` `mode=ro` and selects Telegram sessions.
- A user turn counts as Bittensor-topic when it holds a corpus term: a curated list of protocol words such as subnet, emission, stake, validator, miner, alpha, yuma, commit, childkey, tempo, halving, conviction.
- For each such turn, the report records whether any `atlas_kb`, `atlas_live`, `atlas_fleet` or `atlas_repo` tool row follows before the next user turn.
- Output: counts and session ids only, never message text.

## Risks / Trade-offs

- [Value patterns miss a paraphrased value ("about three hundred dollars")] → Anything without a clean refusal marker is still flagged for the operator. A pattern only widens auto-fail, never auto-pass.
- [More operator classification work per run] → Accepted. The battery runs per grounded spec, not hourly.
- [The retrieval check makes upgrades block more often] → Only when a battery fact leaves the corpus. The block report names the failing suite, and the fix is a battery edit by the operator.
- [The topic word list in the grounding report under- or over-counts] → It is a trend measure. The report states its word list and that it is a heuristic.

## Migration Plan

1. Apply after `knowledge-retrieval`, in the same deploy.
2. After the Pi pull and activation, apply SOUL.md from canon (backup `SOUL.md.bak-wp13-<date>`).
3. Run the device-matches-canon check.
4. Operator `/restart`.
5. With separate operator approval, run one live battery via `run_battery.py` and score it.
6. Record the verdict in `docs/decisions.md`.

Rollback: restore the SOUL backup; `git revert` the battery and scorer commits.

## Open Questions

None.
