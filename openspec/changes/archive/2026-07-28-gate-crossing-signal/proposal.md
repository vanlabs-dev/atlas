# Gate-Crossing Signal

## Why

Subtensor spec 440 (live on Finney 2026-07-27) put a Hill gate on subnet
emission shares: subnets whose demand share sits below the gate bar (theta,
on-chain `EmissionGateBar`) have their emission collapsed toward zero and
redistributed to above-bar subnets. The bar is now the single most
consequential per-subnet chain fact — a crossing in either direction is an
economic cliff event — and nothing in Atlas watches it. The grounding corpus
was updated 2026-07-28 (decisions.md chain-evidence entry); this change adds
the live signal.

## What Changes

- livedata learns the emission-gate state: a minimal, fail-closed chain RPC
  read of `EmissionGateBar` (theta) plus the sudo-settable parameters
  `EmissionBarQuantile` (q) and `EmissionGateExponent` (h), persisted per
  poll — governance moves of q/h become visible instead of silently wrong.
  This is already necessary, not hypothetical: live Finney q was observed
  at 0.75 on 2026-07-28 vs the 0.61 code default, moved by a root-origin
  path that never appears in the AdminUtils extrinsic feed.
- livedata computes each subnet's demand share (`moving_price x
  (1 - miner_burn)`) from the TaoSwap panel it already polls, normalized
  over the chain's emit-to universe — including emission-disabled subnets,
  which the chain zeroes only AFTER the bar is computed — compares it to
  theta, and records durable gate-crossing events with hysteresis (no
  flapping, no stale-data writes, no re-emission on restart) — mirroring
  the existing `spec_version` upgrade-event pattern.
- The Telegram notifier gains a fifth alert class, `gate-crossing`
  (instant tier, per-netuid cooldown): a confirmed crossing pages with
  direction, share vs bar, margin, and source provenance in the established
  single-fact-line style.
- The hourly pass runs the gate poll alongside the existing
  `poll-chain-head` step, before the Telegram scan (same piggyback
  pattern; best-effort, never fails the repo unit).

## Capabilities

### New Capabilities

(none — this extends two existing capabilities)

### Modified Capabilities

- `live-data`: new requirements — emission-gate state polling (theta/q/h
  from a validated live RPC read, fail-closed), demand-share computation
  from the validated TaoSwap panel, and durable hysteresis-guarded
  crossing events that are never written from stale data and never
  re-emitted on restart.
- `telegram-integration`: the operational class list grows from four to
  five — `gate-crossing` joins as a distinct instant-tier class with
  per-netuid cooldown and the established message-style rules.

## Impact

- `livedata/atlas_live.py` + `livedata/config.json`: one new keyless RPC
  provider entry (allowlisted `state_getStorage` on three fixed keys),
  gate-state/gate-event tables in the livedata store, a `poll-gate` CLI.
- `telegram/atlas_telegram.py`: new class adapter reading `var/livedata`
  read-only past a persisted watermark (existing scan machinery).
- Systemd: the hourly `atlas-repotrack-update.service` gains one
  best-effort `ExecStartPost` line (operator `sudo cp` + `daemon-reload`).
- No new inbound ports, no keys/secrets (RPC endpoint is keyless), no new
  Python dependencies (stdlib HTTP, same as existing adapters).
- Rollback: config kill-switch disables the poll and the class; removing
  the ExecStartPost line reverts the schedule.
