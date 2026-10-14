# Spec Delta

## ADDED Requirements

### Requirement: Subnet registration settings are watched

The chain-parameter watch SHALL read `NetworkImmunityPeriod`,
`NetworkLockReductionInterval` and `NetworkRateLimit` from the
SubtensorModule pallet as plain `u64` items on pinned keys, at the gate
poll's finalized block. Each item SHALL be declared in the chain-read list,
so the hourly probe checks it. A value change SHALL record a transition; a
first observation SHALL seed without one.

#### Scenario: Immunity change records a transition

- **WHEN** a watched `NetworkImmunityPeriod` of 864000 is followed by an
  observation of 432000
- **THEN** one chain-parameter transition is recorded with both values

#### Scenario: First observation seeds silently

- **WHEN** `NetworkLockReductionInterval` is observed for the first time
- **THEN** the observation is stored and no transition is recorded

#### Scenario: Declared for the probe

- **WHEN** the chain-read probe runs
- **THEN** it checks all three items against live metadata as `u64`
  storage values with no key hasher
