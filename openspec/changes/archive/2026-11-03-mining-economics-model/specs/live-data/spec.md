## ADDED Requirements

### Requirement: Miner-activity and consensus context is read at the mining snapshot block

Live-data SHALL read, at the finalized block of the mining snapshot, each
subnet's epoch consensus mode, pending pruning target, validator permits,
per-mechanism last-update and weight rows, the registration block of each
UID below the registered count, and the serving block of each axon. Every
item SHALL be declared in the chain-read table, and every substituted
default in the expected-default table.

#### Scenario: Context shares the economics block

- **WHEN** the mining snapshot is read
- **THEN** the context items carry the same block number and hash as the
  economics items

#### Scenario: Context failure does not fail the economics

- **WHEN** a context item fails to read or decode
- **THEN** that context is marked unread for the affected subnets, and the
  economics snapshot still succeeds

#### Scenario: Unknown consensus value fails closed

- **WHEN** a subnet's consensus entry holds an index other than Yuma or Null
- **THEN** that subnet's mode is unread, and no other subnet is affected

#### Scenario: Only the axon serving block is decoded

- **WHEN** an axon entry is read
- **THEN** only its serving block is decoded and returned, and its address,
  port and protocol are neither decoded nor stored

#### Scenario: Registration blocks are read for registered UIDs only

- **WHEN** a subnet has 256 registered UIDs
- **THEN** registration blocks are read for UIDs 0 to 255 and no
  enumerated stale entry is counted

#### Scenario: New reads join the probe

- **WHEN** the chain-read probe runs
- **THEN** it checks each new item's hashers, value type and, where one is
  substituted, its default against live metadata
