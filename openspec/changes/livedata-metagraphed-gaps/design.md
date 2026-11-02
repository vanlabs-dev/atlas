# Design

## Context

- `atlas-live` (`livedata/atlas_live_server.py`) serves eight tools. Each
  tool runs named operations from `livedata/config.json` through
  `run_operation` in `livedata/atlas_live.py`: one HTTP GET, validation
  against a pinned schema in `livedata/schemas/<provider>/`, a
  post-processor, a freshness envelope, and an audit record.
- TaoSwap is keyless. Its 2026-07-12 contract report
  (`contract-taoswap-20260712T013740Z-f50d283e`) found no documented rate
  limit and no rate headers. Config applies `per_minute_cap: 20` and
  `min_spacing_seconds: 1.0`. A `validators_taoswap` operation, a
  post-processor and `taoswap/validators.v1` already exist, but no tool
  uses them.
- Chain reads already have batched `state_queryStorageAt` at one finalized
  block, netuid-keyed key derivation with a prefix self-test,
  `audit_chain_read`, and codecs `u16`, `u64f64` and `bool`.
- TaoSwap's `/v2/subnets/{netuid}/` returns a `hyperparameters` object
  (for example `rho`, `kappa`, `immunity_period`, `tempo`,
  `min_difficulty`, `max_weight_limit`). Some values are strings or
  floats.
- The current schema lists every new endpoint: `/v2/validators/{hotkey}/`,
  `/v2/subnets/{netuid}/validators/`, `/v1/account-ledger/`,
  `/account-transactions/`, `/events/`, `/blocks/{block}/events/`.
- `live_portfolio` already resolves wallet aliases from
  `config.wallet_aliases`.

## Goals / Non-Goals

**Goals:**
- Each new tool reuses `run_operation`, so validation, envelopes, audit
  and retries apply to it unchanged.
- Hyperparameters cite the finalized block wherever the chain stores the
  value.
- Bounded responses, so the phone-sized Telegram answer stays readable.

**Non-Goals:**
- No polling, no stored history, no Telegram alerts from the new data.
- No TaoStats calls.
- No runtime-API (`state_call`) decoding.
- No generic TaoSwap passthrough tool.

## Decisions

1. **Hyperparameters from storage items, not the runtime API.**
   - Read each item from a list in `livedata/config.json`
     (`hyperparams.items`: storage item, codec, hasher, TaoSwap key).
     Use the existing netuid-keyed derivation and self-test, batched at
     one finalized block.
   - Alternative rejected: `state_call` on
     `SubnetInfoRuntimeApi_get_subnet_hyperparams_v2`. It returns every
     value with defaults applied, but it is one SCALE struct whose field
     order changes between runtime specs. A wrong layout decodes into
     plausible wrong numbers, while a wrong storage key fails the
     self-test or reads empty.
   - The item list lives in config, which is inside the upgrade job's edit
     scope, so a runtime that renames an item can be fixed there.
   - The implementation verifies each item's type and hasher against the
     subtensor clone at the live spec before pinning it.
   - New codecs: `u64`, plus any width the verified items need.

2. **TaoSwap fills unset storage and cross-checks the rest.**
   - Substrate does not store ValueQuery defaults, so an unset item reads
     null.
   - Rejected: hard-coding defaults per spec. That repeats the drift risk
     WP5 already tracks.
   - Adopted: take TaoSwap's value and label it `taoswap`, with "chain
     storage unset".
   - Both sides are normalized before comparing: integers from strings,
     `65535.0` to `65535`. The comparison is exact, because these are
     discrete parameters.
   - A mismatch reuses the existing provider-disagreement shape
     (`conflicting`, both values).

3. **One new operation per TaoSwap endpoint.**
   - New operations: `subnet_detail_taoswap`,
     `subnet_validators_taoswap`, `validator_detail_taoswap`,
     `account_ledger_taoswap`, `account_transactions_taoswap`,
     `events_taoswap`, `block_events_taoswap`. Each gets a pinned schema
     and a post-processor.
   - Path parameters (netuid, hotkey, block) are substituted only after
     type and SS58 validation, so no caller text reaches a URL.
   - Rejected: one parameterised "taoswap get" operation. That would be
     the generic surface the spec forbids.

4. **SS58 validation in the standard library.**
   - Check base58 decoding, prefix 42, and the blake2b-512 `SS58PRE`
     checksum. `hashlib.blake2b` is in the standard library.
   - Aliases resolve through `config.wallet_aliases`, as `live_portfolio`
     does.

5. **Caps.**
   - Validators: default 15, maximum 64, as `live_metagraph` does.
   - Ledger, transactions and events: default 20, maximum 50, newest
     first.
   - Each response states the cap and the total count TaoSwap listed.

6. **Discovery first, on the workstation.**
   - Extend `discover_taoswap.py` with the new endpoints. Use two samples
     where the shape varies (a large and a small subnet, an active and an
     idle coldkey), plus negative tests (unknown netuid, malformed
     hotkey).
   - Raise `MAX_CALLS` only as far as those probes need.
   - The report id and its findings, including rate headers if any now
     appear, are recorded in `docs/decisions.md` as the operator gate,
     before the adapters merge.
   - The politeness budget stays unchanged unless the report finds
     documented limits.

## Risks / Trade-offs

- **[TaoSwap's hyperparameter keys or shape change]**: the pinned schema
  fails closed with a health event, and chain values still return.
- **[A hyperparameter item is renamed or retyped at a runtime upgrade]**:
  the self-test or decode fails for that item, which reads as
  `unavailable` or `taoswap`, never a wrong chain value. The upgrade job
  can fix the config list.
- **[TaoSwap disagrees with the chain because its indexer lags]**: the
  conflict is surfaced with both values and the block, and the chain value
  is the one to cite.
- **[Account history is personal data]**: the tool returns only what
  TaoSwap already publishes, and the audit log redacts parameters as it
  does today.
- **[More tool text in Hermes' prompt]**: four short descriptions; MCP
  schemas are already deferred and materialized on use.

## Migration Plan

1. Run discovery, then record the report and the gate in
   `docs/decisions.md`.
2. Build, test, commit, push (with the operator's yes).
3. On the Pi: `git pull --ff-only` in `~/atlas`, then
   `systemctl --user restart hermes-gateway` (each with a yes). Check that
   `atlas-live` registers 12 tools.
4. Operator phone check: one question for each new tool.
5. Rollback: revert the commits and restart the gateway. No stored state
   is added, so there is nothing to migrate back.

## Open Questions

- The exact hyperparameter item list (around 20 items) is fixed during
  implementation from the subtensor source at the live spec. The approach
  and tasks do not depend on which items make the list.
