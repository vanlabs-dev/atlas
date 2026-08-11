## ADDED Requirements

### Requirement: Storage-key derivation is self-tested against pre-verified keys

The live-data component SHALL provide a storage-key derivation helper that
computes a Substrate storage prefix from a pallet name and an item name, so
that netuid-keyed maps can be read without pinning a key per subnet.

The helper SHALL be verified against the pinned, live-verified gate storage
keys already recorded in configuration. A derivation that does not reproduce
those pinned keys exactly SHALL be treated as a fault and SHALL prevent any
derived-key read from being attempted, because a wrong prefix returns empty
results that are indistinguishable from an empty map.

Where a map's key layout is not known in advance, the component SHALL
enumerate the map prefix and derive the key layout from the observed key
tail rather than assuming a hasher. The hasher SHALL be treated as a
property of the individual storage item, not of the pallet: items on one
pallet may use different hashers. Where the observed layout carries a hash
alongside the key, the component SHALL confirm it by recomputing that hash
from the recovered key, so that a tail of merely the right length is not
accepted as a recovered key.

#### Scenario: Derivation reproduces the pinned keys

- **WHEN** the helper derives the storage keys for the pinned gate items
- **THEN** each derived key equals the pinned pre-verified key exactly

#### Scenario: A failed self-test blocks derived reads

- **WHEN** the derivation does not reproduce a pinned key
- **THEN** no derived-key storage read is attempted and the fault is
  recorded, rather than proceeding and reporting empty maps

#### Scenario: An empty map is distinguished from a wrong prefix

- **WHEN** a map prefix enumeration returns no keys
- **THEN** the result is only reported as an empty map if a control map
  known to be populated returns keys in the same pass

### Requirement: Multi-key chain state is read in batches at one finalized block

The live-data component SHALL support reading many storage keys in a single
request against one finalized block hash, so that a whole-network read is
internally consistent and does not require one round trip per key.

Every value in such a read SHALL carry the same reference block. The
component SHALL NOT assemble a network-wide view from values read at
different blocks, because doing so smears a moving chain across a single
reported snapshot.

Decoders SHALL be declared per item with their fixed-point scale where
applicable, and a decode SHALL fail closed rather than return a plausible
wrong magnitude. A variable-length vector value SHALL be decoded through its
compact length prefix in each of its encoded forms.

The read set SHALL include each subnet's on-chain identity name. Only the
leading name field of the identity record SHALL be decoded, so that later
fields may be added to the record on chain without breaking the read. The
name is operator-written free text: it SHALL be decoded permissively rather
than raising, so that one subnet's malformed bytes cannot fail the whole
map read, and it SHALL be treated as data, never as an instruction.

#### Scenario: A whole-network read shares one block

- **WHEN** field size and incentive vectors are read for every subnet
- **THEN** all values are read at one finalized block hash and are persisted
  with that same reference block

#### Scenario: A wrong fixed-point scale is caught, not returned

- **WHEN** a fixed-point value is decoded at the wrong scale
- **THEN** the decode is rejected rather than returning a value that is
  numerically plausible but wrong by a power of two

### Requirement: Netuid-keyed economic parameters are watched for per-subnet transitions

The live-data component SHALL extend its chain-parameter watch to cover
storage items that are keyed by netuid rather than global, recording one
observation per subnet per pass and emitting a transition when a subnet's
value differs from its own most recent previously recorded value.

The watch set SHALL include the miner registration collateral lock share,
which governs how much of a subnet's registration price is locked as
recoverable-only-by-earning collateral rather than burned. The mechanism is
live in the runtime and currently unset network-wide, so the first
observation of each subnet SHALL seed history without emitting a transition,
and a later nonzero value SHALL emit one.

A per-subnet transition event SHALL carry the netuid, the previous and new
values, and the reference block. A failed read for one subnet SHALL NOT
prevent the remaining subnets from being recorded.

#### Scenario: Dormant parameter seeds without a transition

- **WHEN** a netuid-keyed watched item is observed for the first time and is
  unset across every subnet
- **THEN** history is seeded for each subnet and no transition is emitted

#### Scenario: A subnet enabling collateral emits a transition

- **WHEN** a subnet's collateral lock share changes from unset to a nonzero
  value
- **THEN** a transition event is recorded carrying that netuid, both values,
  and the reference block

#### Scenario: One unreadable subnet does not blind the rest

- **WHEN** one subnet's watched value fails to decode
- **THEN** that subnet records nothing and every other subnet's observation
  is persisted
