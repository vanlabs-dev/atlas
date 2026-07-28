# Tasks — Gate-Crossing Signal

## 1. livedata: gate-state RPC provider

- [x] 1.1 Add `gate_signal` config block to `livedata/config.json`:
      enabled kill-switch (default false), RPC endpoint list, the three
      pinned storage keys as hex constants with item names + derivation
      documented in the `_comment`, per-runtime assumed defaults (q 0.61,
      h 3 for spec 440), `hysteresis_pct` default 10, `confirm_polls`
      default 2, `absence_clear_polls` default 3, timeout
- [x] 1.2 Implement the keyless JSON-RPC provider in
      `livedata/atlas_live.py`: fetch `chain_getFinalizedHead` once, then
      `state_getStorage(key, at=hash)` for the three pinned keys; stdlib
      HTTP, bounded retries per existing rules; persist the reference
      block with the observation
- [x] 1.3 Implement typed validation with null semantics: present values
      decode hex → little-endian u128 → U64F64 with bounds checks (theta
      [0,1), q (0,1), h [1,8]; out-of-bounds ⇒ health event, nothing
      persisted); null q/h ⇒ persist the assumed default marked
      `assumed-default`; null/zero theta ⇒ persist gate-inactive
- [x] 1.4 Add `gate_state` table + status surface (theta/q/h history with
      provenance, reference block, last poll, q/h change and
      assumed-default→explicit transitions visible in `livedata status`)

## 2. livedata: shares, sides, and crossing events

- [x] 2.1 Compute demand shares from the validated TaoSwap subnets panel:
      `moving_price x (1 - miner_burn)` over ALL non-root panel subnets
      (emission-disabled included in normalization; `emission_is_enabled`
      carried as annotation); no extra provider calls; no panel ⇒ no
      events
- [x] 2.2 Implement per-netuid gate-side tracking: relative hysteresis
      band around theta + consecutive-poll confirmation; first observation
      seeds silently; absence for `absence_clear_polls` clears the side
      and reappearance re-seeds silently (netuid-reuse guard);
      gate-inactive→active re-seeds all sides silently
- [x] 2.3 Add `gate_events` table (netuid, direction, share, theta,
      prev_side, emission_enabled, observed_at); event identity for
      downstream de-dup is the row id; restart never re-emits
- [x] 2.4 Add the `poll-gate` CLI command (inert when kill-switch off)
      and wire it into the pass ordering after `poll-chain-head`

## 3. telegram: gate-crossing class

- [x] 3.1 Add the `gate-crossing` event adapter to
      `telegram/atlas_telegram.py`: read `var/livedata` gate events
      read-only past a persisted row-id watermark; class absent when
      disabled
- [x] 3.2 Implement instant-tier paging with per-netuid cooldown
      (suppressed events recorded in the ledger, never dropped)
- [x] 3.3 Render the alert body: direction headline + single-fact lines
      (netuid, share, bar, margin, figure sources, emission-disabled note
      when relevant), HTML with plain-text fallback, no em/en dashes;
      extend `init` to seed the new watermark

## 4. Tests (off-device)

- [x] 4.1 livedata provider: decode/bounds fixtures (valid theta/q/h,
      junk hex, out-of-bounds ⇒ health event + nothing persisted), null
      q/h ⇒ assumed-default provenance, null/zero theta ⇒ gate-inactive,
      RPC failure ⇒ fail-closed, assumed-default→explicit transition
      surfaces in status, reference-block persistence
- [x] 4.2 livedata shares/events: normalization includes
      emission-disabled subnets (universe fixture with disabled entries);
      hysteresis matrix (crossing confirmed, wobble inside band, first
      seed silent, restart no-replay); lifecycle matrix (absence clears →
      reappearance seeds without event; gate-inactive→active re-seeds
      without events)
- [x] 4.3 telegram: adapter row-id watermarking, cooldown
      suppress-not-drop, message rendering (style rules incl.
      emission-disabled note), disabled-class inertness
- [x] 4.4 Full suites green: `livedata/tests`, `telegram/tests`

## 5. Deploy (Pi) and acceptance

- [ ] 5.1 `git pull` on the Pi; verify the three pinned keys against the
      live chain FROM the Pi (theta decodes in-bounds; q/h value-or-null
      as expected — q was explicit 0.75 and h null on 2026-07-28); choose
      and record the RPC endpoint; run `poll-gate` once manually to seed
      (silent) and inspect `livedata status`
- [ ] 5.2 Enable `gate_signal.enabled`; run a scan pass end-to-end; send
      a `test --class gate-crossing` alert and confirm delivery
- [ ] 5.3 Operator installs the updated service unit (`sudo cp` +
      `daemon-reload`); verify the hourly pass runs poll-gate before the
      Telegram scan
- [ ] 5.4 Record acceptance in `docs/decisions.md` (evidence: endpoint,
      observed theta/q/h with provenance, seeded sides count, first
      recorded events if any, suppressions); set a calibration read date
      for `hysteresis_pct`/cooldown
