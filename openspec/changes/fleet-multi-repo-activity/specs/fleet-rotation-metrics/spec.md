# Spec Delta

## ADDED Requirements

### Requirement: Activity can combine an organisation's repositories
A subnet's activity SHALL be computed over its on-chain repository plus every eligible repository of the organisation that owns it. Commits SHALL be counted once by commit id across repositories, with the existing windows, bot-author exclusion and epoch scoping. Each pass SHALL record which repositories were counted.

#### Scenario: Activity in a sibling repository
- **WHEN** the on-chain repository has no commit in 90 days and an eligible sibling repository has 12 human commits in the last 30 days
- **THEN** the combined 30-day count is 12 and the subnet is not cold under combined activity

#### Scenario: Mirrored commit
- **WHEN** the same commit id appears in two counted repositories
- **THEN** it is counted once

### Requirement: Organisation-wide reading is limited to single-subnet organisations
A repository SHALL be eligible only when its owner is an organisation, not a personal account; no other current subnet names that owner on chain; it is not a fork and not archived; it was pushed in the last 90 days; and the operator has not excluded it or its organisation. Otherwise the subnet keeps single-repository activity.

#### Scenario: Shared organisation
- **WHEN** three current subnets name repositories of the same organisation on chain
- **THEN** each of them is read from its own on-chain repository only

#### Scenario: Personal account
- **WHEN** the on-chain repository belongs to a personal account
- **THEN** no other repository of that account is read

#### Scenario: Operator exclusion
- **WHEN** the operator excludes a repository in configuration
- **THEN** it is not counted for any subnet from the next pass

### Requirement: Combined activity is shadowed until switched on
Combined figures SHALL be recorded beside the single-repository figures. While `activity.multi_repo` is `shadow`, the board, scores, the cold flag, signals and every export SHALL use the single-repository figures. Only `on` SHALL switch them to combined figures. A report SHALL list, per subnet, both figure sets and the repositories counted.

#### Scenario: Shadow mode
- **WHEN** `activity.multi_repo` is `shadow`
- **THEN** the board and scores are identical to a pass without the feature and the report shows both figure sets

#### Scenario: Switched on
- **WHEN** `activity.multi_repo` is `on`
- **THEN** c7, c30, a30, days since the last commit and the cold flag come from combined activity

### Requirement: Repository listing degrades to single-repository activity
Organisation listings SHALL be refreshed at most daily within the provider's unauthenticated rate limit. A failed refresh SHALL keep the last listing. A listing older than 7 days SHALL NOT be used; the subnet then keeps single-repository activity and the report names the gap.

#### Scenario: Listing call fails
- **WHEN** the listing call for an organisation fails
- **THEN** the pass uses the previous listing and records the failure

#### Scenario: Listing too old
- **WHEN** an organisation's newest listing is 8 days old
- **THEN** its subnet is read from the on-chain repository only and the report says why
