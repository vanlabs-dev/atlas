# Proposal

## Why

The operator finds Atlas Telegram alerts too technical. A review of the
last 28 days of alerts (page: https://claude.ai/artifact/XPVhGFAp3eJnUaTehcdrBi)
found setting names as headlines, raw 65,535-scale chain numbers, undefined
jargon, filler lines, and alerts that ask for an action no one needs to take
(knowledge ingests are activated by the upgrade job, never by the operator).
Templates alone cannot fix this: the plain wording of a change in a chain
rule depends on what the rule does. An LLM rewrite pass can, if code keeps
the facts and checks the numbers.

## What Changes

- New plain-English rewrite pass. After an instant-tier event is built, a
  Hermes one-shot (no tools) rewrites the headline, meaning sentence, key
  figures and body lines in plain language. Code converts units first. A
  check requires every number and every subnet id and name in the rewrite to
  come from the input. Any failure, timeout or refusal sends the
  deterministic template instead. Results cache by content hash.
- Alert layout moves technical detail into the details fold: setting names,
  blocks, run ids, SHAs, file counts, raw values, microsecond timestamps.
  Key figures drop to two. The filler line `Before: stored value. After:
  stored value.` and the repeated `Governs:` line are removed.
- 65,535-scale values (`CollateralLockShare`, `BasketConcentrationCap`)
  render as percentages. Descriptions open in a capital letter and appear
  once.
- Plain terms replace jargon in alerts: "reward cutoff" for the emission bar,
  "demand" for demand share, "version" for runtime spec. The alert lexicon in
  `telegram/config.json` and `telegram/docs/voice.md` changes to match.
  The inbound chat voice is unchanged.
- **Behaviour changes, approved 2026-10-22:**
  - `knowledge-ingestion` moves from `instant` to `briefing`. Its wording
    says the facts are already in use and asks for no action.
  - A gate crossing for a subnet whose TAO switch is already off (the
    "no effect" alert) is recorded and not sent.
  - The rewrite pass may add a `Next:` line where code has none.
  - The stale CoinGecko pinned schema is repaired, which ends the
    `schema-drift` alert that has fired since 2026-09-28.
- The CoinGecko button gap does not exist (checked: all 28 sampled rise
  alerts carry the taostats button), so no fix is planned for it.

## Capabilities

### New Capabilities

- `alert-plain-rewrite`: the rewrite pass, its input and output contract, the
  number and name check, the fallback, the cache, bounds and observability.

### Modified Capabilities

- `telegram-integration`: the rule that headlines and meaning are
  deterministic templates changes to allow the checked rewrite; layout
  moves technical detail to the fold and lists the plain terms;
  `knowledge-ingestion` becomes a briefing-tier class; the no-effect gate
  crossing stops paging; raw-scale parameters render as percentages.

## Impact

- Code: `telegram/atlas_telegram.py` (hook in `notify_scan`, builders for
  chain-parameter, gate-crossing, knowledge-ingestion, repository-update,
  schema-drift, runtime-upgrade), new `telegram/atlas_plain_rewrite.py`,
  `telegram/config.json` (rewrite block, lexicon, tiers),
  `telegram/docs/voice.md`, `livedata/schemas/coingecko/` and
  `livedata/atlas_live.py` for the schema repair.
- Systems: one Hermes one-shot per paged alert on the Pi, reusing the
  existing X OAuth subscription. No new credential. Scan latency grows by
  the model call, bounded by a timeout.
- Not touched: the pulse briefing (editions are disabled), digest messages,
  the effectiveness ledger, the chat voice, the upgrade job's edit scope.
