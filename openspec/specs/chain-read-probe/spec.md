# chain-read-probe Specification

## Purpose
Proves that every storage item Atlas reads still exists on the live chain
with the expected shape, so a runtime rename or removal is caught instead
of read silently as a default.

## Requirements

### Requirement: One declared list of chain reads

The live-data component SHALL declare every storage item it reads in one
table, with pallet, item, key hashers, and value type. The readers SHALL
take their items from that table. A test SHALL fail when a reader reads a
storage item that the table does not declare.

#### Scenario: Undeclared read
- **WHEN** a reader reads a storage item missing from the table
- **THEN** the live-data tests fail naming the item

### Requirement: Probe checks declared reads against live metadata

The probe SHALL fetch runtime metadata at one finalized block through
keyless RPC and SHALL check, for each declared read, that the item exists
in its pallet with the declared hashers and value type. For each declared
read that has an expected default, the probe SHALL also check that the
item's metadata default encodes to exactly the expected bytes. It SHALL
exit non-zero on any mismatch or when the metadata cannot be fetched or
decoded, and its output SHALL name each failing item, the block, and the
spec. A changed default SHALL page in plain words as a changed default,
naming the chain value and the value Atlas assumes.

#### Scenario: Renamed item
- **WHEN** the live runtime no longer has a declared storage item
- **THEN** the probe exits non-zero naming the item and the block

#### Scenario: Metadata unavailable
- **WHEN** no RPC endpoint returns decodable metadata
- **THEN** the probe fails closed with a provider error, not a pass

#### Scenario: Default changed
- **WHEN** the runtime's default for `SubnetOwnerCut` is no longer the value
  Atlas assumes when the item is unset
- **THEN** the probe exits non-zero naming the item, both values and the
  block

### Requirement: Hourly drift health check

The probe SHALL run hourly on the Pi independently of the upgrade job. A
failing probe SHALL page the operator whether or not the spec number
changed, and SHALL NOT repeat the same page for the same failing set until
it changes or clears.

#### Scenario: Drift without a spec change
- **WHEN** the spec is unchanged but a declared item fails the probe
- **THEN** the operator is paged within one hour, once for that failing set

### Requirement: One declared table of expected defaults

The live-data component SHALL declare, in one table next to the chain-read
table, the encoded default it assumes for every storage item whose unset
value it substitutes. Every hard-coded or configured default for a chain
read SHALL equal that table. A test SHALL fail when a code constant or a
configured default for a chain read disagrees with the table, or when a
defaulted item is missing from it.

#### Scenario: Config default drifts from the table
- **WHEN** the gate's configured assumed default for `EmissionBarRank`
  differs from the declared expected default
- **THEN** the live-data tests fail naming the item
