## MODIFIED Requirements

### Requirement: Sensitive output is scrubbed before send

Every outbound Telegram message SHALL pass a fail-closed scrubber before
transmission. A message SHALL be refused (not truncated-and-sent) if it
would contain an API key, a secret path together with its value, an
environment dump, wallet secrets, or private diagnostics exceeding the
approved exposure policy (ATLAS-TG-004). A CLI-flag rule SHALL match only
a flag that starts a word, never a hyphen inside a word. A refusal SHALL
be final, and a fixed notice naming only the class and event id SHALL be
sent instead.

#### Scenario: Message with a secret is refused

- **WHEN** an outbound message body matches a secret/over-exposure pattern
- **THEN** the send is refused, the event is recorded as a scrub failure,
  and no secret-bearing message is transmitted

#### Scenario: Clean message passes

- **WHEN** an outbound message contains only source- and time-labelled
  operational data within the exposure policy
- **THEN** the scrubber passes it and it is sent

#### Scenario: Hyphenated word is not a flag

- **WHEN** a message contains "the subnet-token mechanism"
- **THEN** the scrubber passes it

#### Scenario: Refused alert sends a withheld notice

- **WHEN** an alert is refused by the scrubber
- **THEN** one fixed notice says an alert of that class was withheld,
  gives its event id, and the refused alert is never retried

### Requirement: Delivery is recorded and de-duplicated

The notifier SHALL persist, for every notification event, a 0600 ledger
record containing: event identifier, creation time, attempted delivery
time, delivery status, retry count, and final failure (ATLAS-TG-005). A
delivered event SHALL also record the sent text and the Telegram message
id. The system SHALL avoid duplicate alert floods by de-duplicating on
event identity and coalescing repeats within a configured window.

#### Scenario: Ledger captures the delivery lifecycle

- **WHEN** an event is created, attempted, and resolved (delivered or
  finally failed)
- **THEN** its ledger record carries all six fields with consistent
  timestamps and the final status

#### Scenario: Delivered event keeps its text and message id

- **WHEN** an event is delivered
- **THEN** its ledger record holds the sent text and the message id from
  the Telegram reply

#### Scenario: Duplicate flood is suppressed

- **WHEN** the same event identity recurs within the coalescing window
- **THEN** it is suppressed or coalesced rather than re-delivered, and the
  suppression is recorded

### Requirement: Telegram failure does not affect core operation

A Telegram outage, invalid token, or send failure SHALL be caught and
recorded, and SHALL NOT disrupt Hermes conversation, the repository update
timer, live-data tools, or any other core function (PRD Phase 5 exit
criterion). Retries SHALL be bounded and observable. A message that fails
with a transient status SHALL be kept durably with its rendered content
and retried by later runs for up to 24 hours. A 429 SHALL be honoured
from its `retry_after` value.

#### Scenario: Delivery failure is isolated

- **WHEN** Telegram is unreachable or rejects a send
- **THEN** the failure is recorded with a final status after bounded
  retries, and core Atlas functions continue unaffected

#### Scenario: Transient failure is retried later

- **WHEN** a send fails with a network error or a 5xx status
- **THEN** the rendered message is kept, a later run sends it once, and
  the sent message shows when the event was detected

#### Scenario: Rate limited

- **WHEN** Telegram answers 429 with `retry_after` 30
- **THEN** no further message is sent in that run, and the kept messages
  are not retried before 30 seconds have passed

#### Scenario: Permanent rejection is not retried

- **WHEN** Telegram answers 400, 401, 403 or 404 after every fallback
- **THEN** the event is recorded as failed and is not kept for retry

#### Scenario: Retry window expires

- **WHEN** a kept message is still undelivered 24 hours after it was first
  attempted
- **THEN** it is dropped and recorded as finally failed

### Requirement: Persistent fail-closed state pages once

When a provider, the gate poll, or the chain-parameter watch has recorded
only failures for longer than a configured window, the notifier SHALL page
one message naming the component, the first failure time, and the last
recorded good observation, and SHALL NOT page again for that component
until it has recovered and failed anew. Only provider-failure records
SHALL count toward the first failure time.

#### Scenario: Prolonged outage pages once

- **WHEN** a component has recorded only failures for longer than the window
- **THEN** exactly one message is sent for that outage

#### Scenario: Invariant notes do not set the outage start

- **WHEN** invariant-divergence notes predate the first provider failure
- **THEN** the page and its key use the first provider failure time

## ADDED Requirements

### Requirement: The alert scan runs on its own schedule

The gate poll and the alert scan SHALL run from their own timer, at
least hourly, independent of the repository update. A failed repository
update SHALL NOT skip the gate poll or the alert scan. A failed gate poll
SHALL NOT skip the alert scan.

#### Scenario: Repository fetch fails

- **WHEN** the repository update fails for several hours
- **THEN** the gate poll and the alert scan still run every hour and send
  their alerts

### Requirement: Every Atlas sender goes through the ledger

The probe, the runtime upgrade job, the health watch and the unit failure
notifier SHALL send through the same ledger, scrubber and retry queue as
the alert scan. Each message SHALL have a stable event id, so a retried or
repeated send is de-duplicated.

#### Scenario: Probe drift page

- **WHEN** the probe sends a drift page
- **THEN** the ledger records it with its class, status, text and message
  id

#### Scenario: Probe send fails

- **WHEN** a probe page fails with a transient status
- **THEN** it is kept and retried by a later run, and the probe treats it
  as handed over
