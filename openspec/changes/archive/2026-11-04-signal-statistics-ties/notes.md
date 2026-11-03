# Notes

## Rescore dry run (task 4.2), 2026-11-03

- **Input:** a read-only copy of the Pi signal tables, taken 20:41 NZDT:
  - 1,728 outcomes and 51,342 price rows
  - `gate_events` (124 rows) and `panel_snapshot` anchors (1,497)
- **Registration map:** read live from chain on the workstation.
- **Writes:** none on the Pi.
- **Scored:** 1,558 rows re-scored, 24 gate-crossing entries re-anchored.
- **v2 states:**
  - 1,218 recorded
  - 284 unavailable
  - 56 unverified
  - 1 unscored: a gate-crossing whose re-anchored 7-day window has not
    closed yet.

### Before (old rules, Pi `effectiveness` 2026-11-03 19:55 NZDT)

| class | h | filled | class median | baseline median |
|---|---|---|---|---|
| econ-code | 7 | 403 | -2.746 | -2.231 |
| gate-crossing | 1 | 24 | 0.000 | 0.000 |
| gate-crossing | 7 | 21 | -7.213 | -1.998 |
| gate-crossing | 30 | 10 | -33.404 | -7.495 |
| narrative-cluster | 7 | 33 | -2.839 | -1.341 |
| root-rotation | 7 | 87 | -4.722 | -5.166 |
| watchlist | 7 | 4 | -1.673 | -1.831 |

### After (current rules)

| class | h | filled | events | unavail | unverified | median excess | 95% interval | meets floor | beats |
|---|---|---|---|---|---|---|---|---|---|
| econ-code | 1 | 338 | 210 | 70 | 10 | +0.029 | -0.120 .. +0.203 | | |
| econ-code | 7 | 332 | 206 | 61 | 10 | +0.089 | -0.707 .. +0.809 | yes | no |
| econ-code | 30 | 265 | 162 | 42 (5 re-registered) | 7 | +2.402 | -0.065 .. +3.736 | | |
| gate-crossing | 1 | 20 | 18 | 2 | 2 | -1.528 | -4.338 .. -0.169 | | |
| gate-crossing | 7 | 16 | 14 | 2 | 2 | -3.334 | -12.741 .. +0.010 | no | no |
| gate-crossing | 30 | 7 | 6 | 1 | 2 | -28.831 | none (<10) | | |
| narrative-cluster | 7 | 30 | 7 | 3 | 0 | -0.946 | none (<10) | no | no |
| root-rotation | 7 | 53 | 4 | 25 (1 re-registered) | 9 | -0.877 | none (<10) | no | no |
| root-rotation | 30 | 74 | 5 | 6 (6 re-registered) | 7 | +0.065 | none (<10) | | |
| watchlist | 7 | 2 | 2 | 1 | 1 | +0.748 | none (<10) | no | no |

### Readings (measurement, no recommendation)

- **Gate-crossing 1 day.** The fabricated 0.000% is gone. Measured from
  eligibility, the class trails the baseline by 1.5 points, and the interval
  lies wholly below zero. This is the only instant class with enough events
  for an interval.
- **Root-rotation, retired class.** It now reads 4 to 5 event moments,
  where the old read counted 87 rows. The 6 re-registered rows (SN82, SN92,
  SN116, SN108 and others) are excluded.
- **`no-vector` rate.** At 1 day it is 17% for econ-code and 58 of 87 for
  root-rotation. Vectors are about 6 h apart, so an exit can miss the 6 h
  grace. This is the honest cost of the rule: the grace is a code constant,
  and the timer cadence sets the loss.
- **Promotion.** No class beats the baseline under the interval rule.
  Econ-code meets the event floor (206 moments), and its 7-day interval
  spans zero.

## End-to-end pass (task 7.2), 2026-11-03 07:50 UTC

- **What ran:** one `run_measurement` on the workstation with the real
  `default_price_fetcher`: TaoSwap through the live-data layer, plus
  `read_registration_blocks` over finney RPC.
- **Store:** a scratch copy of the Pi signal tables. The livedata path was
  pointed at the Pi snapshot copy.
- **Newest vector:** 129 rows, all carrying `reg_block`, at block 9424046.
  - Netuid 0 reads 0.
  - SN16 9392863, SN36 9420559, SN82 9155260, SN92 9247819, SN116 9210632.
- **Pass summary:**
  - 24 gate-crossing entries re-anchored
  - 1,559 settled rows scored
  - 5 outcomes filled
- **Gate-crossing, current rules:**

  | h | filled | events | median excess | 95% interval |
  |---|---|---|---|---|
  | 1 | 20 | 18 | -1.566 | -4.377 .. -0.210 |
  | 7 | 17 | 15 | -4.267 | -13.690 .. 0.000 |
  | 30 | 7 | 6 | -28.834 | none (<10) |

- **Fix found here:** the per-pass catch-up scored old gate rows before they
  were re-anchored. Every pass now re-anchors first, with a regression test.
