# Spec Delta

## ADDED Requirements

### Requirement: Rule lines for block-count settings read in days

A chain rule change line for a setting configured with a display label and
the unit `blocks` SHALL name the setting by its label and state the change
in days at 7,200 blocks per day.

#### Scenario: Immunity change in the pulse

- **WHEN** `NetworkImmunityPeriod` moved from 864000 to 432000 inside the
  window
- **THEN** the chain rule changes section shows `New-subnet immunity 120
  days → 60 days`
