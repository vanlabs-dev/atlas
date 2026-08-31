# Network Drift 452

## Why

Atlas is grounded at subtensor spec 443 (corpus re-sync 2026-08-06). Finney
has since run 444 through 452 and has been on 452 since 2026-08-29 (block
8951570). Detection worked: `spec_upgrades` recorded every step and the
`chain-runtime-upgrade` class paged each one. Grounding did not follow, and
three of those releases invalidate claims the knowledge base states with
confidence today:

- **Spec 447 (2026-08-14, PR #3083): the subnet takeover gate is now a single
  hotkey.** Ownership transfers only when one hotkey's own conviction exceeds
  18% of eligible alpha (`SubnetAlphaOut - SubnetProtocolAlpha -
  AlphaBurned`). The aggregate 10% gate is gone. The corpus states the
  aggregate 10% rule twice (`ground-truth.md` lines 94 and 119, the second as
  a "common mistake" correction), so Atlas currently corrects a questioner
  toward the wrong rule.
- **Spec 449 (2026-08-25, PR #3109): Root Reborn curation is ON.** A
  migration flipped `RootWeightSettingEnabled` to true and introduced
  `RootWeightsCap`, pinned to 1/16 (4096/65535), so no destination may take
  more than one sixteenth of a `set_root_weights` vector. Atlas's
  chain-parameter watch recorded the flip on 2026-08-27 at block 8938705 and
  paged it, which is the detection layer doing its job. The corpus still says
  curation is "INSTALLED BUT DORMANT" and instructs the model "do NOT say
  root dividends are being curated" (lines 83, 84, 118). The knowledge base
  is issuing a confident negative that is false, which is the exact failure
  mode the fail-closed design exists to prevent. `RootWeightsCap` itself is a
  new root-settable economic knob and is unwatched.
- **Spec 450 (2026-08-27, PR #3117): beta pricing moved on-chain.** The chain
  now stamps a per-fund `BetaBaseline` at first share mint (marked at
  realizable quotes), accumulates `BasketTwr` as the canonical staker-yield
  series, keeps a NAV-weighted basket index (`BetaIndexSnapshot`), and serves
  display-denominated positions through runtime API v3. The corpus has no
  notion of display units, baselines, or the index, so any question about a
  beta price or a fund's performance has no grounding at all.

Smaller changes ride the same window: spec 445 restored the miner-burn
scaling of demand shares (already in the corpus); spec 448 added a
`TotalAlphaStaked` counter per netuid, `move_stake_limit` with slippage
protection, linked limit orders, and an all-hotkeys unstake workflow; spec
451 hardened basket claims (a terminal swap failure in one holding no longer
blocks healthy root claims, and pending deposits no longer block root stake
changes); spec 452 aligned EVM precompile execution with the current call
frame. New storage also appeared for `LiquidAlphaConsensusMode`,
`TotalVotingPower`, and `ConsensusByMechanism`.

One Atlas-side defect surfaced during the audit. The rank-mode cross-check
has recorded 105 `invariant-divergence` health events in the last seven
days, "above-bar count 31 vs rank 32", on 32 of the last 48 polls. It is not
a share-pipeline defect. The chain recalculates theta every 360 blocks and
holds it fixed between recalculations, while the panel EMA that Atlas
normalises keeps moving; theta changed on 39 of 47 consecutive hourly polls.
The 32nd subnet sits at the bar by definition, and whether it counts as at or
above depends on which side of a rounding boundary two EMA readings land.
The count never diverged by more than one. The configured tolerance is zero,
which turns a boundary artefact into a permanent silent alarm that would mask
a real divergence of two or more.

## What Changes

- **Corpus re-sync 443 to 452**, verified against the merged subtensor code
  at tag v452 and live Finney reads at one finalized block, using the same
  method as the 2026-07-28 and 2026-08-06 re-syncs. Rewritten, not marked:
  the conviction section states the single-hotkey 18% gate; the Root Reborn
  section states curation is live since spec 449 with the 1/16 cap, and adds
  the on-chain beta pricing model (baseline, index, display price, display
  beta, `BasketTwr`); the negative-claim rules that instruct the model to
  deny curation are replaced by rules that date it. Spec 448 and 451 changes
  enter as short factual lines. `stake_into_basket` gating (corpus line 85)
  is re-verified at v452 and stated as found.
- **Benchmark battery extension.** Three adversarial cases pin the corrected
  claims: a takeover-threshold question must answer 18% single-hotkey dated
  to spec 447; a "is root curation live" question must answer yes, dated, and
  name the cap; a beta-price question must refuse a live value and explain
  the display convention. The battery is re-run and re-accepted over the new
  corpus under the existing threshold sheet.
- **`RootWeightsCap` joins the chain-parameter watch** as an independently
  read item at the root netuid entry, with a pinned derived key, `u16` codec,
  the v449 default, and a `governs` description. A transition pages through
  the existing `chain-parameter-change` class.
- **Rank cross-check tolerance becomes one**, and the requirement records why:
  the invariant holds exactly only at the chain's recalculation block. A
  divergence of two or more still records a health event. The 105 recorded
  events are explained in the decision log, not deleted.
- **Alert vocabulary.** The `chain-parameter-change` `governs` map and the
  voice gloss map gain `RootWeightsCap`, beta, basket, basket index, and
  display price so a paged transition or a chat answer never uses a term the
  lexicon cannot gloss.
- **Documentation.** README status, decision log (acceptance entry plus the
  divergence explanation), `knowledge/corpus/SOURCES.md` coverage date.

Not breaking. Additive watch item, one config default change, corpus content.
The model stays `grok-4.5`; a model swap would invalidate the benchmark and
is its own change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `live-data`: the root-settable chain-parameter watch set gains
  `RootWeightsCap` (an independently read, netuid-keyed item observed at the
  root entry); the rank-mode above-bar cross-check tolerates a divergence of
  one by requirement, because the invariant is exact only at the chain's
  theta recalculation block.

The corpus re-sync and battery extension exercise existing `knowledge-base`
requirements (supersession handling, benchmark gate) without changing them.
The `telegram-integration` and `agent-voice` gloss additions are
configuration under existing requirements.

## Impact

- **Code:** `livedata/atlas_live.py` (watch item registration, key
  derivation for a `Blake2_128Concat` netuid-keyed item at netuid 0, `u16`
  decode), `livedata/config.json` (`chain_params.items`,
  `gate_signal.above_count_tolerance`), `livedata/tests`.
- **Content:** `knowledge/corpus/ground-truth.md`, `fact-patterns.md`,
  `negative-claim-rules.md`, `SOURCES.md`, `hashes.json`;
  `knowledge/benchmark` battery and expected-evidence markers.
- **Config:** `telegram/config.json` (`classes.chain-parameter-change.governs`,
  `voice.gloss`).
- **Docs:** `README.md`, `docs/decisions.md`.
- **Device:** corpus ingest, activation, and benchmark run on the Pi; one
  `git pull`; no new service, credential, port, or provider. One additional
  keyless finney storage read per hourly pass.
