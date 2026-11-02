## MODIFIED Requirements

### Requirement: Live evidence tools for Hermes

Hermes SHALL access live data only through named read-only MCP operations
(price, subnets, metagraph, network stats, validators, hyperparameters,
account, events, integration status). There is no generic
query/URL/SQL/shell surface. Errors SHALL be structured
(category, component, retry_safe, user-safe message, correlation id), and
the integration-status tool SHALL report health events, per-provider
last-success, and remaining quota. (ATLAS-TOOL-002/003/004)

#### Scenario: Current-data question answered with provenance

- **WHEN** Hermes is asked a current-price question with the `atlas-live`
  tools available
- **THEN** the answer cites provider and timestamp from the tool's
  metadata envelope (or states unavailability), never an invented value

#### Scenario: Status tool reports health and quota

- **WHEN** `live_status` is called
- **THEN** it returns integration-health events, per-provider
  last-success times, and remaining quota (local estimate vs
  provider-reported)

#### Scenario: Former metagraphed questions have a named tool

- **WHEN** Hermes is asked about validators, a subnet's hyperparameters,
  a coldkey's history, or recent chain events
- **THEN** a named `atlas-live` tool answers it (`live_validators`,
  `live_hyperparams`, `live_account`, `live_events`) with the metadata
  envelope, and no tool accepts a free-form URL, path or query

## ADDED Requirements

### Requirement: Subnet hyperparameters are read chain-first

`live_hyperparams` SHALL read one subnet's hyperparameter storage items
from Finney at one finalized block, with the same key self-test and
fail-closed rules as other chain reads. TaoSwap's subnet record SHALL
supply each value the chain does not store, and SHALL cross-check each
value the chain does store. Every value SHALL carry its source: `chain`
(stored, with block), `taoswap` (chain storage unset, with TaoSwap's
upstream time), or `unavailable`. A value present in both sources that
differs SHALL be returned as a disagreement with both values, never
averaged or silently replaced. Spending TaoStats quota is not permitted.

#### Scenario: Stored values come from the chain

- **WHEN** `live_hyperparams` is called for a netuid whose `Tempo` and
  `ImmunityPeriod` are stored on chain
- **THEN** those values are returned with source `chain` and the finalized
  block number and hash they were read at

#### Scenario: Unset storage is filled from TaoSwap and labelled

- **WHEN** a hyperparameter's storage is unset on chain and TaoSwap
  reports a value for it
- **THEN** the value is returned with source `taoswap` and a note that
  chain storage is unset, never presented as a chain read

#### Scenario: Sources disagree

- **WHEN** a stored chain value and TaoSwap's value for the same item
  differ
- **THEN** the item is returned as `conflicting` with both values and
  their sources

#### Scenario: Chain unreachable

- **WHEN** every configured RPC endpoint fails or the key self-test fails
- **THEN** the tool returns TaoSwap values labelled `taoswap` with a
  health note that the chain read failed, or a structured
  live-unavailable result if TaoSwap also fails

#### Scenario: Unknown netuid

- **WHEN** the netuid is not a registered subnet in both sources
- **THEN** the tool returns a structured not-found error and no values

### Requirement: Validator, account and event data come from keyless TaoSwap

`live_validators`, `live_account` and `live_events` SHALL call TaoSwap
only, through operations covered by an approved TaoSwap contract report.
Each SHALL return a bounded, ranked result (a size cap stated in the
response), validate against a pinned schema before exposure, and carry
the live metadata envelope. Inputs SHALL be validated before any call: a
hotkey or coldkey must be a well-formed SS58 address, and a netuid or
block a non-negative integer. TaoSwap's rate behaviour is recorded from
the contract report and the existing politeness budget applies.

#### Scenario: Validators of one subnet

- **WHEN** `live_validators` is called with a netuid
- **THEN** it returns that subnet's validators ranked by stake, at most the
  stated cap, each with hotkey, identity name, stake, take and yield, plus
  the total count TaoSwap listed

#### Scenario: One validator

- **WHEN** `live_validators` is called with a hotkey
- **THEN** it returns that validator's subnets and top delegators, bounded,
  with the metadata envelope

#### Scenario: Malformed address refused before any call

- **WHEN** `live_account` or `live_validators` gets a value that is not a
  well-formed SS58 address
- **THEN** it returns a structured invalid-input error and makes no
  provider call

#### Scenario: Events for one block

- **WHEN** `live_events` is called with a block number
- **THEN** it returns that block's events with pallet, name and extrinsic
  index, and the block number as the block reference

#### Scenario: Adapter waits for discovery

- **WHEN** a new TaoSwap endpoint has no entry in an approved contract
  report
- **THEN** no tool calls it, and the change's discovery task must run and
  be recorded first
