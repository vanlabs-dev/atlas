# Tasks — Gate-Crossing Signal

## 1. livedata: gate-state RPC provider

- [ ] 1.1 Add `gate_signal` config block to `livedata/config.json`
      (enabled kill-switch default false, RPC endpoint list, storage item
      names, `hysteresis_pct` default 10, `confirm_polls` default 2,
      timeout) with an explanatory `_comment`
- [ ] 1.2 Implement the keyless JSON-RPC provider in
      `livedata/atlas_live.py`: name-derived twox128 storage keys
      (stdlib xxhash-free twox implementation or vendored constant
      derivation), `state_getStorage` POST, bounded retries per existing
      rules
- [ ] 1.3 Implement typed validation: hex → little-endian u128 → U64F64
      with bounds checks (theta [0,1), q (0,1), h [1,8]); failure records
      a health event and writes nothing
- [ ] 1.4 Add `gate_state` table + status surface (theta/q/h history,
      last poll, q/h-change visibility in `livedata status`)

## 2. livedata: shares, sides, and crossing events

- [ ] 2.1 Compute demand shares from the validated TaoSwap subnets panel
      (`moving_price x (1 - miner_burn)` over emission-enabled subnets,
      normalized); no extra provider calls; no panel ⇒ no events
- [ ] 2.2 Implement per-netuid gate-side tracking with the hysteresis
      band and consecutive-poll confirmation; first observation seeds
      silently
- [ ] 2.3 Add `gate_events` table (netuid, direction, share, theta,
      prev_side, observed_at, deterministic event_id); restart never
      re-emits
- [ ] 2.4 Add the `poll-gate` CLI command (inert when kill-switch off)
      and wire it into the pass ordering after `poll-chain-head`

## 3. telegram: gate-crossing class

- [ ] 3.1 Add the `gate-crossing` event adapter to
      `telegram/atlas_telegram.py`: read `var/livedata` gate events
      read-only past a persisted watermark; class absent when disabled
- [ ] 3.2 Implement instant-tier paging with per-netuid cooldown
      (suppressed events recorded in the ledger, never dropped)
- [ ] 3.3 Render the alert body: direction headline + single-fact lines
      (netuid, share, bar, margin, figure sources), HTML with plain-text
      fallback, no em/en dashes; extend `init` to seed the new watermark

## 4. Tests (off-device)

- [ ] 4.1 livedata: RPC decode/bounds fixtures (valid theta/q/h, junk
      hex, out-of-bounds), fail-closed on RPC error, q/h change surfaces
      in status
- [ ] 4.2 livedata: share computation from panel fixtures; hysteresis
      matrix (crossing confirmed, wobble inside band, first-seed silent,
      restart no-replay)
- [ ] 4.3 telegram: adapter watermarking, cooldown suppress-not-drop,
      message rendering (style rules), disabled-class inertness
- [ ] 4.4 Full suites green: `livedata/tests`, `telegram/tests`

## 5. Deploy (Pi) and acceptance

- [ ] 5.1 `git pull` on the Pi; run `poll-gate` once manually with the
      kill-switch off-path (seed + inspect `livedata status`); verify RPC
      endpoint reachability and record the chosen endpoint in
      `docs/decisions.md`
- [ ] 5.2 Enable `gate_signal.enabled`; run a scan pass end-to-end; send
      a `test --class gate-crossing` alert and confirm delivery
- [ ] 5.3 Operator installs the updated service unit (`sudo cp` +
      `daemon-reload`); verify the hourly pass runs poll-gate before the
      Telegram scan
- [ ] 5.4 Record acceptance in `docs/decisions.md` (evidence: seeded
      sides count, first recorded events if any, suppressions); set a
      calibration read date for `hysteresis_pct`/cooldown
