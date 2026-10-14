# Spec Delta

## ADDED Requirements

### Requirement: Block-count settings render in days under a plain label

When a chain-parameter alert concerns a setting configured with a display
label and the unit `blocks`, the headline SHALL name the setting by its
label and state the change in days, and the key figures SHALL show each
value as blocks with its day count at 7,200 blocks per day. The storage
item name SHALL stay visible in the alert.

#### Scenario: Immunity change reads in days

- **WHEN** `NetworkImmunityPeriod` changes from 864000 to 432000
- **THEN** the headline reads `New-subnet immunity changed: 120 days → 60
  days` and the setting line shows `864,000 blocks (120 days) → 432,000
  blocks (60 days)`

#### Scenario: Unlabelled settings keep the current form

- **WHEN** a setting has no configured display label
- **THEN** the alert renders exactly as before
