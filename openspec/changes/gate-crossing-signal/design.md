# Design — Gate-Crossing Signal

## Context

Spec 440's emission gate: normalized demand shares `s_i = price_i x
(1 - miner_burn_i) / sum` pass through `gate(s) = s^h / (s^h + theta^h)`,
then renormalize. Theta is a q-mass bar over the shares, recomputed on-chain
every 360 blocks; q (default 0.61) and h (default 3) are root-sudo-settable
(`sudo_set_emission_bar_quantile` forces a recompute next block). Gate = 1/2
at the bar; below-bar emission collapses toward ~0. Chain evidence and the
grounding update are recorded in `docs/decisions.md` (2026-07-28 entry).

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
  chain, fail-closed.
- Record durable per-subnet crossing events (above↔below the bar) with
  hysteresis so share wobble never flaps alerts.
- Page the operator on confirmed crossings via a new `gate-crossing`
  Telegram class; config kill-switch for the whole feature.

**Non-Goals:**

- No gated-emission-share prediction or APY math (interpretation stays
  with the operator; Atlas records facts).
- No near-bar "hover" digest, no dashboard badge (future candidates; the
  attention board is a separate spec).
- No historical backfill — forward-only from deploy, like the econ gate.
- No websocket subscriptions; hourly polling only.

## Decisions

1. **Theta/q/h are READ from the chain, not recomputed locally.**
   A minimal keyless JSON-RPC provider POSTs `state_getStorage` for three
   fixed storage keys (`twox128(SubtensorModule) ++ twox128(item)` for
   `EmissionGateBar`, `EmissionBarQuantile`, `EmissionGateExponent`),
   stdlib HTTP like every other adapter, typed validation: 16-byte hex →
   little-endian u128 → U64F64 (`raw / 2^64`), bounds-checked (theta in
   [0,1), q in (0,1), h in [1,8]). *Alternative rejected:* recomputing
   theta from TaoSwap shares with a configured q — one sudo call moving q
   or h would make Atlas silently wrong, which violates the fail-closed
   ethos; reading the bar also makes governance moves of q/h visible facts.
   Endpoint(s) are config-listed (default: the public Finney HTTPS
   entrypoint; operator confirms reachability at deploy). RPC failure ⇒ no
   gate-state row, no events, health event recorded — never stale writes.

2. **Demand shares come from the TaoSwap panel already polled.**
   `share_i = moving_price_i x (1 - miner_burn_i)` over subnets with
   `emission_is_enabled`, normalized. This is an approximation of the
   chain's own EMA shares at its bar-update block (different snapshot
   moment, provider rounding); the hysteresis band absorbs the drift and
   the alert body names both sources. *Alternative rejected:* reading ~128
   `SubnetMovingPrice` storage entries per pass via RPC — heavier, and
   duplicates data a validated adapter already delivers.

3. **Hysteresis + confirmation, mirroring the upgrade-event pattern.**
   A subnet's gate side only changes state when its share exits a relative
   band around theta (default ±10% of theta, config `hysteresis_pct`) on
   two consecutive polls (config `confirm_polls`, default 2). First-ever
   observation seeds state silently (no backlog flood — the `init`
   lesson). Crossing events persist `netuid, direction, share, theta,
   prev_side, observed_at, event_id` with a deterministic `event_id`
   (netuid + direction + theta-epoch) for notifier de-dup; restart never
   re-emits (watermark + seeded state, same as spec_version upgrades).

4. **Telegram: fifth class, instant tier, per-netuid cooldown.**
   `gate-crossing` reads the new event table read-only past its own
   watermark. Down-crossings and up-crossings both page (a cliff either
   way); per-netuid cooldown (default 24h) prevents a boundary-hugging
   subnet from paging repeatedly — subsequent events inside cooldown are
   recorded, not paged (never dropped). Message: headline direction line,
   then `netuid N · share X% · bar Y% · margin Z% · shares TaoSwap · bar
   chain RPC` fact lines, HTML with plain-text fallback per the existing
   renderer rules.

5. **Scheduling piggybacks the existing hourly pass.**
   `poll-gate` runs immediately after `poll-chain-head`, before the
   Telegram scan, as another best-effort `ExecStartPost=-…` line. One
   config kill-switch (`gate_signal.enabled`) disables poll + class; the
   unit line removal is the schedule rollback.

## Risks / Trade-offs

- [TaoSwap share vs chain EMA drift near the bar] → hysteresis band +
  2-poll confirmation; alert body carries both numbers and sources so the
  operator can verify; margin shown explicitly.
- [Public RPC endpoint flakiness] → config list allows a fallback
  endpoint; failure is a recorded health event and a skipped pass, never
  stale state; existing bounded-retry rules apply.
- [Storage-key hardcoding breaks if the pallet renames items] → keys are
  derived from names in config, not opaque hex; the hourly repotrack
  alerts on subtensor changes touching these symbols (econ path
  `emission`), so a rename is seen as source change first.
- [q/h sudo change shifts the bar wholesale] → theta is read, so state
  stays correct; a q/h change appears as a recorded parameter change in
  the gate-state history (visible in `livedata status`), and mass
  crossings it causes are real events, rate-limited by cooldown.
- [Alert noise if many subnets sit near the bar] → hysteresis, 2-poll
  confirmation, per-netuid cooldown; calibrate `hysteresis_pct` from the
  first weeks of recorded (not paged) events, like the fleet-signals
  calibration.

## Migration Plan

1. Ship code + config with `gate_signal.enabled: false` (gate-crossing
   class absent from the notifier until enabled) — deploy is inert.
2. On the Pi: `git pull`, run `poll-gate` once manually to seed state
   (silent), inspect `livedata status`, then enable in config.
3. Operator installs the updated service unit (`sudo cp` +
   `daemon-reload`) — the standing privileged-step pattern.
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
