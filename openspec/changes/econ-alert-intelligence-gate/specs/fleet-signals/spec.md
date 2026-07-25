## MODIFIED Requirements

### Requirement: Econ-code changes are detected by path and alerted per range with a per-netuid cooldown
The module SHALL match `files_json` paths of each new change range against
configured econ-code path patterns (reward/incentive/scoring/emission/weights
vocabulary), with the same vendor/test exclusions, to identify **candidates**.
Detection SHALL use recorded path metadata only (no blob fetch). A candidate
SHALL NOT be emitted directly; it SHALL be routed through the econ-alert
intelligence gate, which reads the diff and returns a significance verdict, and
the gate's outcome SHALL determine emission: a `high`/`med` verdict emits one
instant-tier event per matching `(netuid, change-range)` listing matched files,
commit count, and the verdict; a `low` verdict queues a digest line; a `none`
verdict emits nothing but SHALL be recorded. Emission SHALL be deduplicated by
change-range id. Cooldown SHALL be significance-aware: after an instant
econ-code event for a netuid, further **`med` or `low`** matching candidates
within the configured cooldown window (default 24 h) SHALL queue digest lines
referencing the open alert instead of paging, while a **`high`** verdict SHALL
break through the cooldown and page; the cooldown SHALL suppress paging only,
never recording. When the gate cannot judge a candidate it SHALL emit an
`unjudged` instant event rather than dropping it, subject to the same dedup and
cooldown-breakthrough rules as a `med` verdict.

#### Scenario: Reward-path commit alerts once when material
- **WHEN** a change range touches files matching econ-code patterns, the gate returns a `high` or `med` verdict, and no cooldown is active for the netuid
- **THEN** exactly one instant econ-code event is emitted for that range, listing the matched files and carrying the verdict

#### Scenario: Cosmetic reward-path commit does not alert
- **WHEN** a change range matches econ-code patterns but the gate returns a `none` verdict and no high-stakes path is touched
- **THEN** no instant event and no digest line are emitted, and the verdict is recorded for audit

#### Scenario: Busy subnet is dampened, not silenced
- **WHEN** further `med` or `low` econ-matching candidates arrive for the same netuid within the cooldown window
- **THEN** they are recorded and queued as digest lines referencing the open alert, and no instant event is emitted

#### Scenario: A material change breaks through cooldown
- **WHEN** a `high`-verdict econ candidate arrives for a netuid already within its cooldown window
- **THEN** it pages as an instant econ-code event rather than being demoted to a digest line
