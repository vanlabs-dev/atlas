## MODIFIED Requirements

### Requirement: Econ-code changes are detected by path and alerted per range with a per-netuid cooldown
The module SHALL match `files_json` paths of each new change range against
configured econ-code path patterns (reward/incentive/scoring/emission/weights
vocabulary), with the same vendor/test exclusions, to identify **candidates**.
Detection SHALL use recorded path metadata only (no blob fetch). A candidate
SHALL NOT be emitted directly; it SHALL be routed through the econ-alert
intelligence gate, which reads the diff and returns a significance verdict, and
the gate's outcome SHALL determine emission: a `high`/`med` verdict emits one
event per matching `(netuid, change-range)` listing matched files,
commit count, and the verdict; a `low` verdict queues a digest line; a `none`
verdict emits nothing but SHALL be recorded. The delivery of an emitted event
SHALL be governed by the notifier's tier registry: a `high` event is
delivered under `econ-code` and every other event under `econ-code-minor`,
each at its registered tier, so the significance verdict continues to drive
detection, cooldown, and the ledger while the registry alone decides whether
anything pages. Emission SHALL be deduplicated by
change-range id. Cooldown SHALL be significance-aware: after an emitted
econ-code event for a netuid, further **`med` or `low`** matching candidates
within the configured cooldown window (default 24 h) SHALL queue digest lines
referencing the open alert instead of emitting, while a **`high`** verdict SHALL
break through the cooldown and emit; the cooldown SHALL suppress emission only,
never recording. When the gate cannot judge a candidate it SHALL emit an
`unjudged` event rather than dropping it, subject to the same dedup and
cooldown-breakthrough rules as a `med` verdict.

#### Scenario: Reward-path commit alerts once when material
- **WHEN** a change range touches files matching econ-code patterns, the gate returns a `high` or `med` verdict, and no cooldown is active for the netuid
- **THEN** exactly one econ-code event is emitted for that range, listing the matched files and carrying the verdict, and it is delivered according to the registered tier for its significance

#### Scenario: Cosmetic reward-path commit does not alert
- **WHEN** a change range matches econ-code patterns but the gate returns a `none` verdict and no high-stakes path is touched
- **THEN** no event and no digest line are emitted, and the verdict is recorded for audit

#### Scenario: Busy subnet is dampened, not silenced
- **WHEN** further `med` or `low` econ-matching candidates arrive for the same netuid within the cooldown window
- **THEN** they are recorded and queued as digest lines referencing the open alert, and no event is emitted

#### Scenario: A material change breaks through cooldown
- **WHEN** a `high`-verdict econ candidate arrives for a netuid already within its cooldown window
- **THEN** it emits an econ-code event rather than being demoted to a digest line

#### Scenario: A high verdict does not page while the class is demoted
- **WHEN** a `high`-verdict econ-code event is emitted while the econ-code class is registered at the briefing tier
- **THEN** the event is recorded, entered into the effectiveness ledger, and carried in the briefing, and no page is sent

#### Scenario: Only a high verdict pages
- **WHEN** econ events with `high` and `med` verdicts are emitted while `econ-code` is `instant` and `econ-code-minor` is `shadow`
- **THEN** the `high` event pages, the `med` event is recorded and entered into the effectiveness ledger, and no page is sent for it
