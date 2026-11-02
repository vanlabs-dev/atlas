# Tasks

## 1. Discovery gate

- [x] 1.1 Extend `livedata/discover_taoswap.py` with probes for `/v2/subnets/{netuid}/` (two netuids), `/v2/subnets/{netuid}/validators/`, `/v2/validators/{hotkey}/`, `/v1/account-ledger/` and `/account-transactions/` (an active and an idle coldkey), `/events/`, and `/blocks/{block}/events/`, plus negative tests: an unknown netuid and a malformed hotkey. Raise `MAX_CALLS` only to what the probes need. Verify: a test in `livedata/tests/` asserts every new path is probed and the call count stays at or under `MAX_CALLS`.
- [x] 1.2 Run the discovery on the workstation. Record the report id, observed shapes, nullability, pagination and any rate headers in `docs/decisions.md`, together with the metagraphed decision (disabled 2026-11-02, OAuth only). Verify: the report exists under `var/livedata/`, and the decisions entry names its id.

## 2. Validators

- [x] 2.1 Add the `subnet_validators_taoswap` and `validator_detail_taoswap` operations, with pinned schemas under `livedata/schemas/taoswap/`, post-processors and envelopes. Reuse `validators_taoswap` for the ranked list. Verify: fixture tests from the discovery samples pass validation, and a drifted fixture fails closed with a health event.
- [x] 2.2 Add the stdlib SS58 validator (base58, prefix 42, blake2b `SS58PRE` checksum) and alias resolution through `config.wallet_aliases`. Verify: tests accept known-good addresses and reject a bad checksum, a wrong length and non-base58 text, each with no provider call.
- [x] 2.3 Add the `live_validators` tool (no argument, `netuid`, or `hotkey`; `limit` defaulting to 15, maximum 64). Verify: server tests cover all three modes, the cap, the total count, the metadata envelope and the invalid-input error.

## 3. Account and events

- [ ] 3.1 Add the `account_ledger_taoswap`, `account_transactions_taoswap`, `events_taoswap` and `block_events_taoswap` operations, with schemas, post-processors and envelopes. Verify: fixture validation tests, plus a drift test for each schema.
- [ ] 3.2 Add the `live_account` tool (coldkey or alias, `limit` defaulting to 20, maximum 50, newest first) and the `live_events` tool (optional `block`, same limits). Verify: server tests cover a bounded output, a stated cap, the block reference on block events, and a refused malformed coldkey.

## 4. Hyperparameters chain-first

- [ ] 4.1 From the subtensor clone at the live spec, list the per-netuid hyperparameter storage items with their type and hasher. Pin them in `livedata/config.json` under `hyperparams.items`, mapping each to its TaoSwap key. Add the codecs they need (`u64` at least). Verify: a test derives every item key, passes the prefix self-test, and decodes a recorded payload for each codec.
- [ ] 4.2 Add `subnet_detail_taoswap` and the hyperparameter read: chain items batched at one finalized block, TaoSwap fill for unset storage, normalized exact comparison, and per-item `chain`, `taoswap`, `conflicting` or `unavailable` status. Verify: tests cover each source label, a conflict, chain-down fallback, TaoSwap-down with chain values, both down, and an unknown netuid.
- [ ] 4.3 Add the `live_hyperparams` tool (`netuid` required). Verify: a server test returns block number and hash for chain values, and an audit record is written for both the chain read and the TaoSwap call.

## 5. Integration and docs

- [ ] 5.1 Update the `atlas-live` module docstring tool list and `live_status` provider coverage, then run `python3 tools/readme_sync.py`. Verify: `python3 tools/readme_sync.py --check` passes.
- [ ] 5.2 Run every Python suite with the handover loop. Verify: all suites pass, with `hardening/apply/tests` at 0 tests as already known.
- [ ] 5.3 Deploy after operator approval: push, `git pull --ff-only` in the Pi's `~/atlas`, restart `hermes-gateway`. Verify: the gateway log shows `atlas-live` registering 12 tools, and the operator gets an answer on the phone for one question per new tool.
