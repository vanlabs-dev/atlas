# Design — Gate-Crossing Signal

## Context

Spec 440's emission gate: normalized demand shares `s_i = price_i x
(1 - miner_burn_i) / sum` pass through `gate(s) = s^h / (s^h + theta^h)`,
then renormalize. Theta is a q-mass bar over the shares, recomputed on-chain
every 360 blocks; q and h are root-sudo-settable
(`sudo_set_emission_bar_quantile` forces a recompute next block). Gate = 1/2
at the bar; below-bar emission collapses toward ~0. Chain evidence and the
grounding update are recorded in `docs/decisions.md` (2026-07-28 entry).

Live observations that shaped this design (verified 2026-07-28 via raw
`state_getStorage` against Finney):

- `EmissionGateBar` = 0.00925 (theta exists, bar active).
- `EmissionBarQuantile` = **0.75 — already moved from the 0.61 code
  default**, by a root-origin path invisible in the AdminUtils extrinsic
  feed (sudo/multisig-wrapped). Assuming defaults locally would already be
  wrong, three days after the upgrade.
- `EmissionGateExponent` = **null** — never explicitly set; the runtime
  default (3) applies but the raw key is empty. Substrate `ValueQuery`
  defaults are applied at the runtime API layer, NOT written to storage, so
  raw reads of unset parameters return null and this is normal.
- Chain code fact (v440 `subnet_emissions.rs` / `get_subnets_to_emit_to`):
  the share set the bar is computed over includes `SubnetEmissionEnabled =
  false` subnets — they are zeroed only afterwards in
  `get_subnet_block_emissions`. At the July snapshot ~49 of ~126 subnets
  were emission-disabled, so filtering them out of normalization would
  inflate every share by ~60% and place subnets on the wrong side of the
  bar.

Current Atlas state this builds on:

- livedata polls TaoSwap keyless; its subnets panel already validates and
  surfaces `moving_price`, `emission_miner_burn` (0–100%), and
  `emission_is_enabled` per netuid. The hourly `poll-chain-head` CLI runs
  before the Telegram scan via `ExecStartPost` on the repotrack service.
- The `spec_version` upgrade-event pattern (live-data spec) is the model
  for durable, no-stale-writes, no-re-emit event recording.
- The Telegram notifier scans `var/*` stores read-only past persisted
  watermarks; classes are config-listed; message style is single-fact
  lines, `·` separators, never em dashes.

## Goals / Non-Goals

**Goals:**

- Persist the live gate state (theta, q, h) each hourly pass, from the
  chain, fail-closed, with null-storage semantics handled explicitly.
- Record durable per-subnet crossing events (above↔below the bar) with
  hysteresis so share wobble never flaps, surviving restarts, netuid
  reuse, and gate enable/disable transitions without false alerts.
- Page the operator on confirmed crossings via a new `gate-crossing`
  Telegram class; config kill-switch for the whole feature.

**Non-Goals:**

- No gated-emission-share prediction or APY math (interpretation stays
  with the operator; Atlas records facts).
- No near-bar "hover" digest, no dashboard badge (future candidates; the
  attention board is a separate spec).
- No historical backfill — forward-only from deploy, like the econ gate.
- No websocket subscriptions; hourly polling only.
- No reconstruction of q/h change provenance (extrinsic archaeology);
  values are read, changes are recorded as observations.

## Decisions

1. **Theta/q/h are READ from the chain via pinned, pre-verified storage
   keys — never recomputed or assumed locally.**
   A minimal keyless JSON-RPC provider reads three fixed keys
   (`twox128("SubtensorModule") ++ twox128(item)`), computed offline and
   verified against live Finney on 2026-07-28:
   - `EmissionGateBar`
     `0x658faa385070e074c85bf6b568cf05557c9b0d2964cc73e7519676c3cc4d5df9`
   - `EmissionBarQuantile`
     `0x658faa385070e074c85bf6b568cf0555a772007dde2ed63e0f21b5f9d7f16650`
   - `EmissionGateExponent`
     `0x658faa385070e074c85bf6b568cf055588c70e8dd0cf4af3aeb977ba2eee1df4`
   Keys are pinned as hex constants in config with their names and
   derivation documented alongside — no runtime hashing implementation.
   *Alternative rejected:* deriving keys at runtime from names (a pure-
   Python xxhash64 just to rehash three constants is complexity without
   safety: a pallet rename breaks either form equally, is caught by the
   hourly repotrack watch on the subtensor source, and is re-verified at
   deploy). *Alternative rejected:* recomputing theta from panel shares
   with an assumed q — disproven by observation: live q is 0.75, not the
   0.61 default, and the change was invisible in the AdminUtils feed.

2. **All three reads happen at one finalized block.**
   The poll first fetches `chain_getFinalizedHead`, then issues each
   `state_getStorage(key, at=hash)` against that hash, and persists the
   reference block with the observation. This prevents a bar update (every
   360 blocks) from straddling the reads, and gives gate-state rows the
   same reference-block anchoring the `spec_version` pattern has.

3. **Null storage is a defined state, not an error.**
   Substrate does not write `ValueQuery` defaults to storage, so:
   - theta null or 0 ⇒ **gate disabled/uncomputed**: persist the state as
     gate-inactive; produce no crossing events; sides are re-seeded
     silently when the gate becomes active again.
   - q or h null ⇒ **runtime default in effect**: persist the observation
     with the known per-runtime default (q 0.61, h 3 for spec 440, from
     the grounding corpus) marked `assumed-default`, so a later explicit
     sudo set is visible as a provenance change, not just a value change.
   Out-of-bounds decoded values (theta outside [0,1), q outside (0,1), h
   outside [1,8]) remain hard validation failures: health event, nothing
   persisted.

4. **Demand shares come from the TaoSwap panel already polled — normalized
   over the chain's emit-to universe, NOT filtered to emission-enabled.**
   `share_i = moving_price_i x (1 - miner_burn_i)` over all non-root
   subnets in the validated panel, normalized. Emission-disabled subnets
   stay IN the normalization (matching the chain's bar computation,
   verified in the v440 code); `emission_is_enabled` becomes an annotation
   on events and alerts (a crossing by a disabled subnet is informational
   — it earns zero either way). The panel is an approximation of the
   chain's emit-to set (it cannot see `SubtokenEnabled` or
   registration-allowed); the hysteresis band absorbs the residual drift
   and the alert body names both sources. *Alternative rejected:* reading
   ~128 `SubnetMovingPrice` storage entries per pass via RPC — heavier,
   and duplicates data a validated adapter already delivers.

5. **Hysteresis + confirmation + lifecycle guards, mirroring the
   upgrade-event pattern.**
   A subnet's gate side only changes state when its share exits a relative
   band around theta (default ±10% of theta, config `hysteresis_pct`) on
   two consecutive polls (config `confirm_polls`, default 2). Guards:
   - First-ever observation seeds the side silently (no backlog flood —
     the `init` lesson).
   - A subnet absent from the panel for `absence_clear_polls` consecutive
     polls (default 3) has its side cleared; reappearance seeds silently.
     This is the netuid-reuse guard: deregistration hands the netuid to a
     new subnet, and a stale side must not produce a phantom crossing.
   - A gate-disabled→enabled transition re-seeds every side silently.
   Crossing events persist `netuid, direction, share, theta, prev_side,
   emission_enabled, observed_at`; the event identity for notifier de-dup
   is the store row id (the `change_ranges.id` watermark pattern), not a
   semantic hash. Restart never re-emits (watermark + seeded state).

6. **Telegram: fifth class, instant tier, per-netuid cooldown.**
   `gate-crossing` reads the new event table read-only past its own
   watermark. Down-crossings and up-crossings both page (a cliff either
   way); per-netuid cooldown (default 24h) prevents a boundary-hugging
   subnet from paging repeatedly — subsequent events inside cooldown are
   recorded, not paged (never dropped). Message: headline direction line,
   then `netuid N · share X% · bar Y% · margin Z% · shares TaoSwap · bar
   chain RPC` fact lines, plus an `emission disabled` note when relevant;
   HTML with plain-text fallback per the existing renderer rules.

7. **Scheduling piggybacks the existing hourly pass.**
   `poll-gate` runs immediately after `poll-chain-head`, before the
   Telegram scan, as another best-effort `ExecStartPost=-…` line. One
   config kill-switch (`gate_signal.enabled`) disables poll + class; the
   unit line removal is the schedule rollback.

## Risks / Trade-offs

- [TaoSwap share vs chain EMA drift near the bar] → hysteresis band +
  2-poll confirmation; alert body carries both numbers and sources so the
  operator can verify; margin shown explicitly.
- [Panel emit-to approximation (no SubtokenEnabled/registration
  visibility)] → the missing flags affect few subnets and shift all
  shares uniformly; hysteresis absorbs it; documented as an approximation
  in the alert provenance.
- [Public RPC endpoint flakiness] → config list allows a fallback
  endpoint; failure is a recorded health event and a skipped pass, never
  stale state; existing bounded-retry rules apply.
- [Pallet/item rename breaks pinned keys] → deploy-time live verification
  reads all three keys and requires theta to decode in-bounds; the hourly
  repotrack watch alerts on subtensor changes touching emission code, so
  a rename is seen as a source change first; keys re-verified then.
- [q/h changes are invisible as extrinsics (root/multisig-wrapped)] → by
  design we read values, not call feeds; a change appears as a recorded
  parameter-change observation (and `assumed-default` → explicit
  transitions are visible).
- [Netuid reuse after deregistration] → absence-clears + silent re-seed
  (Decision 5); a new tenant of a netuid never inherits the old side.
- [Alert noise if many subnets sit near the bar] → hysteresis, 2-poll
  confirmation, per-netuid cooldown; calibrate `hysteresis_pct` from the
  first weeks of recorded (not paged) events, like the fleet-signals
  calibration.

## Migration Plan

1. Ship code + config with `gate_signal.enabled: false` (gate-crossing
   class absent from the notifier until enabled) — deploy is inert.
2. On the Pi: `git pull`, run `poll-gate` once manually to seed state
   (silent); verify the three pinned keys against the live chain from the
   Pi (theta decodes in-bounds; q/h value-or-null as expected); inspect
   `livedata status`; record endpoint choice and observed theta/q/h in
   `docs/decisions.md`.
3. Enable in config; operator installs the updated service unit
   (`sudo cp` + `daemon-reload`) — the standing privileged-step pattern.
4. Rollback: flip `enabled` false (or revert the unit line). Store tables
   are additive; no migration of existing data.

## Open Questions

- Which public Finney HTTPS RPC endpoint(s) to pin as defaults (verify
  reachability + TLS from the Pi at deploy; candidates: the official
  entrypoint, OnFinality public). Decide on-device, record in
  decisions.md.
- Whether up-crossings should share the same cooldown pool as
  down-crossings per netuid (proposed: yes, simplest) — confirm at
  calibration read.
