# Network Drift 443

## Why

Atlas is grounded at subtensor spec 440 (corpus re-sync 2026-07-28). Finney
has since run 441, 442, and 443 (mainnet on 443 since 2026-08-04). Atlas's
detection layer worked — `spec_upgrades` recorded all three and the
`chain-runtime-upgrade` class paged — but detection without grounding leaves
Atlas reporting *that* the runtime changed while unable to say *what*
changed. Two of those changes matter, and one of them silently invalidated an
assumption inside a shipped capability:

- **The emission gate bar is no longer a q-mass quantile.** Spec 441
  (PR #3014) added `EmissionBarRank` (N): when N > 0, theta is pinned to the
  Nth-largest positive demand share, and the q-mass path runs only at N = 0.
  Chain-verified 2026-08-06: `EmissionBarRank` is unset on Finney, so its
  `ValueQuery` default of **32** applies — rank mode is ACTIVE, and the
  explicit `EmissionBarQuantile` of 0.75 that Atlas records every hour is
  inert. Atlas's gate poll never reads rank, so every `gate_state` row since
  2026-08-03 attributes the bar to a mechanism the chain is not running, and
  a `sudo_set_emission_bar_rank` call would move the bar under every subnet
  with no visible cause. Crossing detection itself is unaffected: theta is
  read from chain storage rather than recomputed, which is why this produced
  no bad alerts.
- **Root Reborn is live** (spec 441, mainnet 2026-08-03). Root dividends now
  reinvest into per-validator beta baskets under a global escrow coldkey,
  only root-registered hotkeys earn root dividends (the remainder is
  recycled), root unstakes sit behind a hold interval, and calls 122/123 are
  retired. But the launch is gated: chain-verified 2026-08-06,
  `RootWeightSettingEnabled` is false, so every fund runs the null strategy
  and dividends accumulate in place. The mechanism is installed and dormant.
  The economically material event is the governance flip of
  `sudo_set_root_weight_setting_enabled`, and nothing in Atlas watches it.

The corpus is wrong on both topics today, and the chain knobs that now govern
them are unwatched. The general shape — a root-settable parameter whose flip
changes network economics without an AdminUtils extrinsic trail — is the same
problem the gate poll already solved for q and h.

The deployed store shows two further defects that are already realised, not
hypothetical. The 441 migration reset the bar on 2026-08-03: Atlas's theta
dropped 14.5% in one poll (0.008884 to 0.007598, then 0.007321), and at
21:06 four subnets — 49, 67, 79, 81 — recorded `rose-above` in a single pass
with shares of 0.0086 to 0.0094. Their demand did not rise; the bar came down
onto them.

- **A bar-parameter change produces exactly |M − N| simultaneous crossings.**
  The per-netuid cooldown is no defence, since every event is a different
  netuid. This burst was only four because the chain tuned the default to be
  near-neutral (28 sides above at the 07-28 seeding, plus 4, is the 32 above
  today). A governance move from rank 32 to 64 would page 32 alerts at once.
- **Those four alerts were affirmatively misleading**, reporting a chain rule
  change as per-subnet demand movement. That is a correctness problem in what
  Atlas told the operator, not merely noise.

Rank mode also hands Atlas a correctness oracle it was not built to use. In
rank mode exactly N subnets sit above the bar, by construction — and
`gate_sides` reads exactly **32 above / 96 below** right now. Atlas's
independently computed panel-derived shares reproduce the chain's rank-32 pin
exactly. That agreement is a free standing check on the panel data, the
normalization universe, and the theta read together.

## What Changes

- The gate poll learns the bar's selection mode: it additionally reads
  `EmissionBarRank` at the same finalized block and persists it with each
  observation, along with the derived bar mode (`rank` when N > 0, `q-mass`
  when N = 0). Rank is a SCALE `u16`, not the `U64F64` the existing three
  items use, so the poll gains a second decoder. Null rank persists the
  documented runtime default marked `assumed-default`, matching the existing
  q/h null semantics.
- **A bar-parameter change re-seeds every subnet's side silently** instead of
  storming, reusing the lifecycle guard the gate pass already applies to a
  gate-inactive to gate-active transition. The single parameter alert carries
  the story and states that per-subnet pages were withheld, so the silence is
  legible rather than looking like a gap.
- **Crossings record the previous observation's theta**, so a bar that moved
  onto a stationary subnet is never rendered as a subnet whose demand rose. A
  rank-pinned bar is itself a demand share and therefore moves on its own,
  which makes this attribution necessary rather than cosmetic.
- Gate-crossing alerts name the active mode and the bar's movement, so a
  crossing is self-describing rather than implicitly attributed to a quantile
  that may not be in play.
- **The rank invariant becomes a standing check**: each rank-mode pass
  persists the above-bar count beside the effective N and raises a health
  event on divergence beyond a tolerance. It never suppresses events or
  discards a pass — a divergence means Atlas and the chain disagree about
  demand, which is information.
- livedata gains a **chain-parameter watch** over all four root-settable
  knobs: the three bar parameters (`EmissionBarRank`, `EmissionBarQuantile`,
  `EmissionGateExponent`), whose values flow from the gate poll's existing
  reads rather than being read a second time, plus `RootWeightSettingEnabled`
  read independently. Observations persist per pass and value transitions
  become durable events. This **supersedes the existing ephemeral
  `params_changed` flag**, which detects q/h changes today but is never
  persisted and never paged — one mechanism, consistent coverage. Items are
  discrete, so transitions need no hysteresis, and a first observation seeds
  without emitting one.
- The watch is **not gated by the emission-gate kill-switch**. Rolling back
  the gate signal must not silently stop watching the Root Reborn curation
  switch, which is unrelated to the gate and is the thing you would most want
  to keep seeing during a rollback.
- The Telegram notifier gains a sixth alert class,
  `chain-parameter-change` (instant tier, no cooldown): a confirmed
  transition pages with the item, both values, the reference block, what the
  change governs, and — where the pass re-seeded sides — that the bar was
  re-priced for every subnet.
- The grounding corpus is re-synced 440 → 443: the emission-gate section is
  rewritten for rank-pinning (q-mass demoted to the N = 0 fallback), a Root
  Reborn section is added covering the live mechanism and its dormant
  curation gate, and negative-claim rules are added for both. This is a data
  refresh under the existing `knowledge-base` requirements (hash-verified
  ingest, recorded provenance, supersession handling) — same as the
  2026-07-28 re-sync — so it carries no spec delta.

Not in scope: the SN9 crossing flap observed 2026-08-04/05 (three crossings
in ~30h despite the 10% hysteresis band). That is a calibration question and
belongs in the gate calibration read due ~2026-08-11, with a fortnight of
events behind it.

## Capabilities

### New Capabilities

(none — this extends two existing capabilities and refreshes corpus data)

### Modified Capabilities

- `live-data`: the emission-gate polling requirement grows to include
  `EmissionBarRank`, the derived bar mode, and the hand-off of decoded bar
  parameters to the watch (a second decoder for the u16 payload, and
  null-as-documented-default semantics extended to rank); the crossing-events
  requirement gains a lifecycle guard re-seeding all sides on a bar-parameter
  change and persists the previous observation's theta per event; a new
  requirement covers the chain-parameter watch; and a further new requirement
  covers the rank-mode above-bar-count cross-check.
- `telegram-integration`: the operational class list grows from five to six
  — `chain-parameter-change` joins as a distinct instant-tier class; the
  existing gate-crossing class additionally names the active bar mode and
  attributes bar-driven crossings to the bar rather than to the subnet.

Unchanged: `knowledge-base`. The corpus re-sync is data work already governed
by its existing requirements.

## Impact

- `livedata/atlas_live.py` + `livedata/config.json`: one more pinned storage
  key in the gate item set plus a `chain_params` item list (key, codec,
  default, description per item); `u16` and `bool` decoders alongside
  `decode_u64f64`; additive `rank` / `rank_provenance` / `bar_mode` /
  `above_count` columns on `gate_state` and a `prev_theta` column on
  `gate_events` (existing rows stay NULL); new `chain_params` and
  `chain_param_events` tables; the ephemeral `params_changed` flag retired in
  favour of the durable path; the re-seed lifecycle guard added to
  `run_gate_pass` beside the existing gate-reactivation guard.
- `telegram/atlas_telegram.py`: one new class adapter reading
  `var/livedata` read-only past its own watermark (existing scan machinery);
  added bar-mode and bar-movement lines in the gate-crossing body.
- `knowledge/corpus/` + the IntoOps `references/` source of truth:
  `ground-truth.md`, `fact-patterns.md`, `negative-claim-rules.md` updated
  upstream first, then re-snapshotted with refreshed `hashes.json` and
  `SOURCES.md`; re-ingest and retrieval-benchmark re-run on the Pi.
- No new schedule, ports, secrets, or Python dependencies. The RPC endpoint
  is the keyless one already in use, and the added reads are allowlisted
  `state_getStorage` calls on pinned keys.
- Rollback: config kill-switches disable the chain-parameter watch and its
  Telegram class independently of the gate signal; the corpus re-sync
  reverts by restoring the prior snapshot and re-ingesting.
