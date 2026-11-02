# Proposal

## Why

The metagraphed MCP server now requires an OAuth sign-in. It has returned
401 to Hermes since at least 2026-10-25, and the operator disabled it in
`~/.hermes/config.yaml` on 2026-11-02 (audit WP2). Hermes lost four groups
of answers with it: validator detail, per-subnet hyperparameters, account
history, and chain events. The operator decision is that chain RPC answers
first wherever the chain can, and keyless TaoSwap answers the rest. No
TaoStats quota is spent and no third-party sign-in is needed.

## What Changes

- Add four read-only `atlas-live` MCP tools:
  - `live_validators`: every validator ranked by stake, one subnet's
    validators, or one hotkey with its subnets and delegators, from TaoSwap
    (`/v2/validators/`, `/v2/subnets/{netuid}/validators/`,
    `/v2/validators/{hotkey}/`). The `validators_taoswap` operation and
    its schema already exist but no tool exposes them.
  - `live_hyperparams`: one subnet's hyperparameters, read from Finney
    storage at one finalized block. TaoSwap's `hyperparameters` object
    (`/v2/subnets/{netuid}/`) fills values the chain does not store and
    cross-checks the ones it does. Every value names its source, and a
    disagreement is reported as a disagreement.
  - `live_account`: one coldkey's ledger and transfers from TaoSwap
    (`/v1/account-ledger/`, `/account-transactions/`).
  - `live_events`: recent chain events, optionally for one block, from
    TaoSwap (`/events/`, `/blocks/{block}/events/`).
- Extend `livedata/discover_taoswap.py` to the new endpoints and produce a
  new contract report before any adapter is built, as the live-data spec
  requires.
- Add pinned schemas, post-processors, and freshness envelopes for each
  new operation. Every answer carries the existing metadata envelope
  (provider, completion time, upstream timestamp, block, freshness).
- Out of scope: metagraphed's health incidents, subnet API and endpoint
  listings, semantic search, and `ask`. They have no keyless equivalent.
  `atlas-kb` covers corpus search. Re-enabling metagraphed stays a one-line
  operator choice and is not part of this change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `live-data`: the "Live evidence tools for Hermes" requirement gains the
  four tools. A new requirement covers chain-first hyperparameter reads
  with a labelled TaoSwap fill. A new requirement covers the TaoSwap
  validator, account and event operations.

## Impact

- Code: `livedata/atlas_live.py` (operations, post-processors, the chain
  hyperparameter read), `livedata/atlas_live_server.py` (four tool
  definitions and handlers), `livedata/config.json` (operations,
  envelopes, the hyperparameter item list), `livedata/schemas/taoswap/`
  (new pinned schemas), `livedata/discover_taoswap.py`, and
  `livedata/tests/`.
- Upgrade job: `livedata/*.py` and `livedata/config.json` are inside its
  edit scope. A future runtime change to a hyperparameter storage item can
  be fixed there. Tests stay outside its scope.
- Pi: one new TaoSwap contract report under `~/atlas/var/livedata/`. After
  the pull, `hermes-gateway` restarts so the `atlas-live` MCP child loads
  the new tools. The WP2 memory verifier is unaffected, because MCP tools
  are not toolsets.
- Providers: TaoSwap call volume grows only with operator questions; there
  is no new polling. The existing politeness budget stays in force.
- Docs: `README.md` tables through `tools/readme_sync.py` if the tool list
  is generated, and `docs/decisions.md` for the metagraphed decision.
