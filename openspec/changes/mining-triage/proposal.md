## Why

Atlas can say what every subnet's code is doing and what the chain is
paying, but nothing joins the two into the only question with money
attached: is there a subnet where a new independent miner would earn
anything. Answering it by hand means reading 104 clones and pricing each
against chain state, roughly 50 to 100 hours, stale within weeks.

Verification on 2026-08-07 established the answer is computable today and
costs nothing: the emission gate already removes 43 of 129 subnets, owner
self-mining (`MinerBurned`) removes 10 more outright, and the chain
`Incentive` vector shows reward is winner-take-most, with 3 to 15 earners
per subnet and the top ten taking essentially all of it. Every input is
keyless. The screen consumes zero TaoStats quota.

## What Changes

- New read-only mining triage collector `fleet/atlas_fleet_mining.py`,
  running inline and fail-isolated in the existing 6h fleet pass. No new
  systemd unit, port, credential, or provider contract.
- `livedata/atlas_live.py` gains a `twox128` helper and a batched
  `read_subnet_maps()` over `state_queryStorageAt`, returning
  `SubnetworkN`, the `Incentive` vector, `MinerBurned`, and
  `CollateralLockShare` per netuid at one block hash. All network access
  stays behind the existing provider boundary, audit table, and retry
  policy; nothing in `fleet/` opens a socket.
- Economics screen: emission-gate cut, a burn cut at 99 percent or above,
  miner-accessible alpha as `alpha_out_emission x 0.41 x (1 - miner_burn)`,
  concentration from the chain incentive vector, constant-product exit
  haircut against pool depth, and net TAO per month against a staking
  baseline. Because `alpha_out_emission` is a protocol constant of one alpha
  per block on every subnet, the ranking is driven by alpha price, burn, and
  concentration, not by emission quantity.
- Feasibility screen over the existing FTS index: `min_compute.yml`,
  miner entrypoint, GPU tells, closed-API tells, each with `file:line`
  evidence, sha-gated like the emission-redirect scan.
- A ranked cut ladder where every excluded subnet keeps its cut reason, a
  second LAN-only board page at `var/fleet/www/mining.html`, and three
  read-only tools on the existing `atlas-fleet` MCP server
  (`mining_board`, `mining_subnet`, `mining_history`).
- `CollateralLockShare` added to the chain-parameter watch. The mechanism
  is live in code since spec 435 and dormant chain-wide today; a subnet
  enabling it changes that subnet's entry risk completely and must surface
  as a transition, not a quietly different number.
- Roadmap re-sequenced: this lands ahead of Phase 6, so `prd.md` §22 and
  the README "Next step" are corrected in the same change.

Not breaking. All tables are additive, all tools read-only, no existing
behaviour changes.

## Capabilities

### New Capabilities
- `mining-triage`: chain-and-code joined screen ranking subnets by what a
  new independent miner could earn, with cut reasons, `file:line`
  feasibility evidence, a LAN-only board, and a read-only query surface.

### Modified Capabilities
- `live-data`: adds keyless batched subnet-map reads
  (`state_queryStorageAt`) and a `twox128` storage-key derivation helper
  with a pinned-key self-test, and extends the chain-parameter watch to
  cover `CollateralLockShare`.
- `fleet-search`: the `atlas-fleet` MCP server gains three read-only
  mining tools; existing tools are unchanged.

## Impact

- New: `fleet/atlas_fleet_mining.py`, `fleet/tests/test_mining.py`,
  `var/fleet/www/mining.html` (gitignored output).
- Modified: `livedata/atlas_live.py`, `fleet/atlas_fleet_server.py`,
  `fleet/atlas_fleet.py` (pass hook), `fleet/config.json` (GPU rent bands,
  cut thresholds), `fleet/README.md`, `prd.md` §22, `README.md`,
  `docs/decisions.md` (collateral watch entry).
- Store: three additive tables in `var/fleet/fleet.db` (`mine_econ`,
  `mine_feasibility`, `mine_state`), with a 90-day prune on `mine_econ`.
- External load: one keyless TaoSwap panel call and a handful of keyless
  finney RPC calls per 6h pass. Zero TaoStats quota.
- Out of scope and unchanged: running or operating a miner, wallet keys,
  registration, signing. PRD §7 holds without exception.
