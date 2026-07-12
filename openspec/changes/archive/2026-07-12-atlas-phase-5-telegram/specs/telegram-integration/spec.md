## ADDED Requirements

### Requirement: Inbound gateway uses the supported Hermes mechanism

The inbound Telegram conversation channel SHALL be the native NousResearch
Hermes gateway, configured by the operator per current official Hermes
documentation (ATLAS-TG-001). Atlas contributes no gateway code — only a
setup note and acceptance verification. The bot token SHALL live only in the
Pi's 0600 `~/.hermes/.env` (`TELEGRAM_BOT_TOKEN`) or equivalent gateway
config; it MUST NOT appear in the repository, logs, chat output, or any
command line.

#### Scenario: Token is never exposed

- **WHEN** the gateway is running and any output (logs, chat, ledger,
  audit) is produced
- **THEN** the bot token value does not appear in it, and no repository
  file contains the token value

### Requirement: Access restricted to allowlisted identifiers

The Telegram bot SHALL accept commands and return operational data only
from explicitly allowlisted numeric Telegram user identifiers
(`TELEGRAM_ALLOWED_USERS`, and the group-scoped equivalents where groups
are used). Unknown users SHALL receive no operational data (ATLAS-TG-002).
Allowed identifiers are operator-supplied device configuration and MUST NOT
be committed to the repository.

#### Scenario: Approved account can query Hermes

- **WHEN** an allowlisted user sends a message to the bot
- **THEN** Hermes processes it and replies through the gateway

#### Scenario: Unauthorized account is rejected

- **WHEN** a user whose numeric ID is not allowlisted messages the bot
  (including inside an allowed group)
- **THEN** the bot returns no operational data and the attempt is not
  serviced

### Requirement: Commands are explicitly allowlisted and non-destructive

Non-admin Telegram commands SHALL be limited to an explicit allowlist
(`user_allowed_commands`). Destructive system administration over Telegram
SHALL be out of scope for this release; no command SHALL mutate the device,
Hermes memory/skills outside existing approval gates, or any wallet
(ATLAS-TG-006). Atlas holds no wallet secrets and none SHALL be reachable
through Telegram.

#### Scenario: Non-allowlisted command is refused

- **WHEN** a non-admin allowlisted user issues a command not in
  `user_allowed_commands` (and not `/help` or `/whoami`)
- **THEN** the command is not executed

#### Scenario: No destructive administration path exists

- **WHEN** the command surface is reviewed
- **THEN** no Telegram command performs destructive system administration
  or any wallet operation

### Requirement: Supported initial scope

The initial Telegram scope SHALL include conversation with Hermes and
outbound operational notifications for three event classes: repository
update, live-provider API schema-drift, and knowledge-ingestion
completion/review-needed (ATLAS-TG-003). Investment and portfolio alerts
SHALL be deferred (PRD Phase 7). Service-failure notifications are deferred
until a Hermes service unit exists; the notifier design SHALL leave that
class addable without rework.

#### Scenario: An enabled class delivers

- **WHEN** a repository update, a schema-drift health event, or a
  knowledge-ingestion event occurs and the class is enabled
- **THEN** a source- and time-labelled notification is delivered once to
  the allowlisted operator

#### Scenario: Deferred classes are absent

- **WHEN** the notifier configuration is reviewed
- **THEN** no investment/portfolio alert class is present, and adding
  service-failure later requires only a new event adapter, not a redesign

### Requirement: Sensitive output is scrubbed before send

Every outbound Telegram message SHALL pass a fail-closed scrubber before
transmission. A message SHALL be refused (not truncated-and-sent) if it
would contain an API key, a secret path together with its value, an
environment dump, wallet secrets, or private diagnostics exceeding the
approved exposure policy (ATLAS-TG-004).

#### Scenario: Message with a secret is refused

- **WHEN** an outbound message body matches a secret/over-exposure pattern
- **THEN** the send is refused, the event is recorded as a scrub failure,
  and no secret-bearing message is transmitted

#### Scenario: Clean message passes

- **WHEN** an outbound message contains only source- and time-labelled
  operational data within the exposure policy
- **THEN** the scrubber passes it and it is sent

### Requirement: Delivery is recorded and de-duplicated

The notifier SHALL persist, for every notification event, a 0600 ledger
record containing: event identifier, creation time, attempted delivery
time, delivery status, retry count, and final failure (ATLAS-TG-005). The
system SHALL avoid duplicate alert floods by de-duplicating on event
identity and coalescing repeats within a configured window.

#### Scenario: Ledger captures the delivery lifecycle

- **WHEN** an event is created, attempted, and resolved (delivered or
  finally failed)
- **THEN** its ledger record carries all six fields with consistent
  timestamps and the final status

#### Scenario: Duplicate flood is suppressed

- **WHEN** the same event identity recurs within the coalescing window
- **THEN** it is suppressed or coalesced rather than re-delivered, and the
  suppression is recorded

### Requirement: Telegram failure does not affect core operation

A Telegram outage, invalid token, or send failure SHALL be caught and
recorded, and SHALL NOT disrupt Hermes conversation, the repository update
timer, live-data tools, or any other core function (PRD Phase 5 exit
criterion). Retries SHALL be bounded and observable.

#### Scenario: Delivery failure is isolated

- **WHEN** Telegram is unreachable or rejects a send
- **THEN** the failure is recorded with a final status after bounded
  retries, and core Atlas functions continue unaffected
