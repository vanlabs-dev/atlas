# triage (stale snapshot)

**This folder is an August 2026 snapshot. Nothing in Atlas reads it, and its
figures are not current.** The last change here was 2026-08-11.

It holds the one-off research batches, the candidate list and
`miner_economics.py`, which computed a payback figure and an earn rate at the
snapshot price. Those ideas now live in the mining screen:

- The live board is `fleet/atlas_fleet_mining.py`. The fleet pass writes it
  every 6 hours, and it is served as `mining.html` and through the
  `atlas-fleet` MCP tools.
- Payback, earning counts and the entrant model are specified in
  `openspec/specs/mining-triage/spec.md` (change: mining-economics-model).

Do not quote numbers from this folder as current.
