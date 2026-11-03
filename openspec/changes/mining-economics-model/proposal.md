# Proposal

## Why

The 2026-11-02 audit (items D1 to D6, D9, D10) found that the mining board ranks
on a figure no real entrant would earn.
- The headline is the parity mean. SN8 shows 147.6 alpha/day, but its median
  independent earner gets 0.09.
- With no budget band, the board is a gross-revenue list.
- The feasibility scanner calls 17 GPU miners "possible".
- The sale haircut covers only the entrant's own sale.
- A full subnet with a 1-block immunity period ranks 20th.
- The MCP board returns 45 raw columns per row.

The operator decided the model on 2026-11-03:
- **Budget band:** `consumer-gpu`.
- **Rent:** priced from Lium.
- **Zero-earning slots:** idle slots that rotate out. They are not competitors
  and not a divisor.

## What Changes

- **BREAKING (model):** the entrant figure is the lower of the parity share and
  the 25th-percentile independent earner, in alpha per day. `MODEL_VERSION`
  goes to 3, so consumers suppress top-ten deltas across the change.
- Each mechanism stores its parity figure, p25 earner and median earner. The
  subnet row carries "N earning of M slots" as context. Slots that earn
  nothing are not a divisor and do not cut.
- **New cut rung `prune-risk`:** it fires when a subnet is full and its
  immunity period is below `mining.min_immunity_blocks` (default 720, about
  two tempos). It sits after winner-take-all and before feasibility.
  Unknown fullness or immunity never cuts.
- **Hardware is costed per subnet.** Each subnet gets the band its evidence
  needs:
  - no GPU evidence: `cpu`
  - declared VRAM: the smallest band that covers it
  - GPU evidence with no declared VRAM: `consumer-gpu`, marked as assumed
    (operator decision 2026-11-03; assuming 80 GB would cut 13 subnets on a
    guess)
  - unknown or unscanned: the budget band, flagged as assumed

  The hardware rung cuts when the required band is above the budget band. Net
  is gross minus that band's rent.
- With no budget band set, every survivor is unrated `no-budget-band`.
  Gross is never ranked as if it were net.
- The staking baseline is removed. It applied an APY to rent, not to capital.
- **Config:**
  - `budget_band` is `consumer-gpu`.
  - Rent is from Lium on 2026-11-03 at TAO $222.13:
    - consumer-gpu: 1.5 TAO/month (RTX 4090 secure, $0.45/h)
    - datacenter-gpu: 6.3 TAO/month (H100 spot, $1.95/h)
  - The rent source and date are recorded in config.
- **The haircut is subnet-wide:** the slippage of selling
  `alpha_out_day x mining.subnet_sale_fraction` (default 1.0) into today's
  pool. Each row stores `pool_days` (pool alpha over daily emission).
- Every price-based figure is labelled "at today's spot price" on the board
  and in the MCP output.
- **Payback days:** registration burn divided by net TAO per day, null when
  net is not positive.
- **Scanner (`SCAN_VERSION` 4):**
  - Scans every file in the miner subtree, plus the entrypoint and
    `min_compute`.
  - Strong code tokens (`torch.cuda`, `.cuda(`, `"cuda"`, `cuda:N`, `vllm`,
    `sglang`, `flash_attn`, `bitsandbytes`, `tensorrt`, `nvidia-smi`, CUDA
    base images, `xformers`, `onnxruntime-gpu`, `cupy`) give `needs-gpu`.
  - Weak mentions (`gpu`, `nvidia`, `h100`, `a100`, `rtx NNNN`, `vram`) are
    recorded as `gpu-mention` evidence and change no verdict.
  - `possible` renders as "no GPU evidence found".
- **Compact MCP:** `mining_board` returns a fixed compact row and drops
  "enter at rank". `mining_subnet` keeps the full detail.
- `triage/` gets a README that marks it as an August 2026 snapshot that
  nothing reads.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `mining-triage`:
  - The headline entrant figure and its "not on incumbent income" rule.
  - The cut ladder: adds the prune-risk rung, a per-subnet required band, and
    a block when no band is set.
  - Feasibility evidence.
  - New requirements for the at-spot label and the subnet-wide haircut,
    payback, and the compact query surface.

## Impact

- **Code:**
  - `fleet/atlas_fleet_mining.py`: economics, ladder, scanner, view, render
    and schema.
  - `fleet/atlas_fleet_server.py`: tool descriptions and the compact board.
  - `fleet/config.json`
  - `fleet/tests/`
  - `subnt/tests` fixtures, if columns move.
  - A new `triage/README.md`.
- **Store:**
  - `mine_econ` gains `pool_days`, `payback_days` and `required_band`.
  - `mine_mechanism` gains `parity_alpha_day`, `indep_p25_alpha_day` and
    `indep_median_alpha_day`.
  - Additive `ALTER` only. `ensure_schema` gains a `mine_mechanism`
    migration.
  - The read-only MCP path must tolerate a store that has not yet migrated.
- **Pi:** a code pull and one mining pass (it migrates and writes a model-3
  pass). The next fleet pass rescans all 107 slots under the new scanner.
  Telegram `/restart` loads the MCP change. No unit change.
- **Not touched:** `livedata/`, the upgrade job, the WP10 rewrite and judge,
  and the web export.
- **Left to WP6:**
  - The fixture export publishes `net_tao_month` and `cut_reason`. With a
    band set, net leaks rent and `above-budget-band` names the band, which
    `subnt-publish` bans. The hyphenated form escapes the banned-string list.
    Operator decision 2026-11-03: hold all fixture exports until WP6 fixes
    this.
  - Labels and verdict wording.
