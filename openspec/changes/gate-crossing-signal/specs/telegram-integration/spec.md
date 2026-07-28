# telegram-integration — Delta: gate-crossing signal

## MODIFIED Requirements

### Requirement: Supported initial scope

The Telegram scope SHALL include conversation with Hermes and outbound
operational notifications for five event classes: repository update, live-provider
API schema-drift, knowledge-ingestion completion/review-needed, live
chain-runtime-upgrade (ATLAS-TG-003), and emission-gate crossing. Investment and
portfolio alerts SHALL be deferred (PRD Phase 7). Service-failure notifications
are deferred until a Hermes service unit exists; the notifier design SHALL leave
that class addable without rework.

#### Scenario: An enabled class delivers

- **WHEN** a repository update, a schema-drift health event, a
  knowledge-ingestion event, a live chain-runtime-upgrade, or a confirmed
  emission-gate crossing occurs and the class is enabled
- **THEN** a source- and time-labelled notification is delivered once to the
  allowlisted operator

#### Scenario: Deferred classes are absent

- **WHEN** the notifier configuration is reviewed
- **THEN** no investment/portfolio alert class is present, and adding
  service-failure later requires only a new event adapter, not a redesign

## ADDED Requirements

### Requirement: Gate-crossing is an instant-tier class with per-netuid cooldown

The notifier SHALL page confirmed emission-gate crossing events (either
direction) as a distinct instant-tier class, reading the livedata
gate-event store read-only past a persisted watermark. Alerts within a
per-netuid cooldown window SHALL be recorded but not paged — never dropped.
The alert body SHALL state the netuid, direction, demand share, bar value,
margin, and the source of each figure (panel-derived share vs chain-read
bar) as single-fact lines in the established message style (HTML with
plain-text fallback, no em or en dashes), and SHALL note when the crossing
subnet is currently emission-disabled (the crossing is informational — the
subnet earns zero either way). When the class is disabled it SHALL be
absent from the scan without affecting the other classes.

#### Scenario: Confirmed crossing pages once

- **WHEN** the scan finds an unseen confirmed gate-crossing event outside
  the netuid's cooldown window
- **THEN** one alert is delivered stating direction, share, bar, margin,
  and figure sources, and the event is marked in the delivery ledger

#### Scenario: Cooldown records without paging

- **WHEN** a further crossing event for the same netuid falls inside the
  cooldown window
- **THEN** the event is recorded in the ledger as suppressed and no page is
  sent

#### Scenario: Disabled class is inert

- **WHEN** the gate-crossing class is disabled in configuration
- **THEN** the scan processes the other classes unchanged and no
  gate-crossing watermark advances
