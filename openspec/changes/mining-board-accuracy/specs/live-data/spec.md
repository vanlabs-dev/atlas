## ADDED Requirements

### Requirement: Chain storage reads are audited

Every chain storage read that live-data makes for another component SHALL
leave an audit record. Each record covers one read at one block and carries:
- the endpoint
- the method
- the storage items and the count of keys requested and returned
- the finalized block number and hash
- request and response times
- the result, with its error category on failure

Storage values SHALL NOT be retained as trusted data. A failed read SHALL be
audited with its error before the failure is returned to the caller.

#### Scenario: Batched read is audited

- **WHEN** the mining screen reads its chain snapshot through live-data
- **THEN** one audit record per read names the items, the key counts, and
  the block

#### Scenario: Failed read is audited

- **WHEN** a chain read fails
- **THEN** an audit record with the error category is written, and the
  caller receives the failure

### Requirement: Double-map and account-keyed storage is read at the same block

Live-data SHALL support reading storage whose keys include account
identifiers. That includes subnet-and-hotkey double maps and coldkey-keyed
maps, derived with each item's declared hashers. Such a read SHALL run at
the same finalized block as the netuid-keyed read it accompanies. Every
item read this way SHALL be declared in the single chain-read table, so the
probe checks its hashers and value type against live metadata.

A key-count cap SHALL bound these reads. When the cap would be exceeded,
the read SHALL fail closed for the affected subnet, never truncate
silently.

#### Scenario: Owner hotkeys resolve at the snapshot block

- **WHEN** the mining screen resolves the owner UIDs of every subnet
- **THEN** owner coldkeys, their hotkeys, and those hotkeys' UIDs are all
  read at the snapshot's block

#### Scenario: Undeclared account-keyed read

- **WHEN** a reader reads an account-keyed item missing from the chain-read
  table
- **THEN** the live-data tests fail naming the item

#### Scenario: Cap exceeded fails closed

- **WHEN** a subnet owner's coldkey owns more hotkeys than the cap
- **THEN** that subnet's owner set is recorded unread, its owner
  reconciliation fails, and it receives no net figure
