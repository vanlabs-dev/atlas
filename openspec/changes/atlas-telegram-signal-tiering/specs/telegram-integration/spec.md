## MODIFIED Requirements

### Requirement: Supported initial scope

The Telegram scope SHALL include conversation with Hermes and outbound
operational notifications for four event classes: repository update, live-provider
API schema-drift, knowledge-ingestion completion/review-needed, and live
chain-runtime-upgrade (ATLAS-TG-003). Investment and portfolio alerts SHALL be
deferred (PRD Phase 7). Service-failure notifications are deferred until a Hermes
service unit exists; the notifier design SHALL leave that class addable without
rework.

#### Scenario: An enabled class delivers

- **WHEN** a repository update, a schema-drift health event, a
  knowledge-ingestion event, or a live chain-runtime-upgrade occurs and the class
  is enabled
- **THEN** a source- and time-labelled notification is delivered once to the
  allowlisted operator

#### Scenario: Deferred classes are absent

- **WHEN** the notifier configuration is reviewed
- **THEN** no investment/portfolio alert class is present, and adding
  service-failure later requires only a new event adapter, not a redesign

## ADDED Requirements

### Requirement: Repository alerts are tiered by significance

The notifier SHALL classify each tracked commit range as `significant` or
`churn` before deciding how to notify. Classification SHALL be deny-by-default:
`churn` is an explicit configured allowlist of non-protocol top-level directories
(e.g. `.github/`, `docs/`, `website/`, `vendor/`, `sdk/`), and a range SHALL be
`churn` only when its changed paths are provably a subset of that allowlist and
no runtime `spec_version` change is recorded. Every other range — a
`spec_version` change, a touch of any protocol-facing directory (`pallets/`,
`runtime/`, `precompiles/`, `common/`), a touch of any top-level directory not in
the churn allowlist, or a range whose recorded file list is known-incomplete
(truncated or non-fast-forward) — SHALL be `significant`. Classification SHALL be
derived from recorded facts (changed file paths and the recorded `spec_version`
delta), not re-fetched from the remote.

#### Scenario: Spec bump or protocol change is significant

- **WHEN** a tracked range changes the runtime `spec_version` or touches a
  protocol-facing directory
- **THEN** the range is classified `significant`

#### Scenario: Only-allowlisted churn is churn

- **WHEN** a tracked range touches only churn-allowlisted paths (`.github/`,
  `docs/`, `website/`, `vendor/`, `sdk/`) and records no `spec_version` change
- **THEN** the range is classified `churn`

#### Scenario: Unknown directory or incomplete record escalates

- **WHEN** a tracked range touches a top-level directory not in the churn
  allowlist, or its recorded file list is truncated or from a non-fast-forward
- **THEN** the range is classified `significant` rather than `churn`

### Requirement: Churn is digested, never paged and never dropped

Churn ranges SHALL NOT trigger an immediate notification and SHALL NOT be
silently discarded. Because the repository-update watermark advances past
processed ranges (churn included), a churn range SHALL be written to durable
pending-digest storage in the same operation that advances the watermark past it,
so it cannot be lost between scans. The notifier SHALL coalesce pending churn
into a low-priority digest that is carried by the next significant repository
alert or emitted as a periodic summary, and SHALL clear a range from pending
storage only once it has been included in a delivered digest. The digest SHALL
identify the coalesced ranges (head SHAs and dominant area) so the operator
retains an audit trail of skipped churn.

#### Scenario: Churn does not page immediately

- **WHEN** a churn range is detected and no significant range accompanies it
- **THEN** no immediate alert is sent and the range is durably retained as
  pending digest state before the watermark advances past it

#### Scenario: Churn survives across scans until digested

- **WHEN** the watermark advances past a churn range and later scans run before
  any significant alert
- **THEN** the churn range remains in pending storage and is not lost, and is
  still eligible for the next digest

#### Scenario: Pending churn rides the next significant alert

- **WHEN** a significant range is notified while churn ranges are pending
- **THEN** the significant alert includes a digest line naming the pending churn
  ranges, and the pending state is cleared

### Requirement: Significant repository alerts carry a concise breakdown

A significant repository alert SHALL include a breakdown built from the recorded
change range: commit count, top changed areas, notable commit subjects or PR
references, tags crossed, and the `spec_version` delta. The breakdown SHALL reuse
the machine-generated summary already recorded by the repository tracker and
SHALL pass the outbound scrubber unchanged; no un-scrubbed diff content SHALL be
sent.

#### Scenario: Breakdown reflects the recorded range

- **WHEN** a significant range is delivered
- **THEN** the message body states the commit count, top changed areas, and the
  `spec_version` delta drawn from the recorded change range

### Requirement: Repository and live-chain state are explicitly distinguished

Every repository alert SHALL mark itself as a source-code (repository) event,
distinct from the live chain, and SHALL state both the tracked-repository
`spec_version` and the current live `spec_version` with their delta. The live
`spec_version` SHALL be read read-only from the live-data store. A repository
alert SHALL NOT imply that the live chain changed.

#### Scenario: Repo alert states both clocks

- **WHEN** a repository alert is delivered and a live `spec_version` is available
- **THEN** the message shows the repository `spec_version`, the live
  `spec_version`, and their delta, and is labelled a repository (source-code)
  event

#### Scenario: Live spec unavailable degrades honestly

- **WHEN** the live `spec_version` cannot be read
- **THEN** the repository alert is still delivered, marked as a repository event,
  and states that the live comparison is unavailable rather than omitting the
  distinction

### Requirement: Live chain-runtime-upgrade is a distinct high-priority class

The notifier SHALL provide a `chain-runtime-upgrade` class that fires when the
live runtime `spec_version` changes, based on the live-data upgrade record. Its
message SHALL be marked as a live-chain (enacted) event, distinct from repository
alerts, and SHALL state the previous and new live `spec_version` and the
reference block. Crossing a governance threshold (e.g. conviction ownership at
`spec_version` ≥ 425) SHALL be surfaced within this class.

#### Scenario: Live spec change fires a chain upgrade alert

- **WHEN** the live-data store records a live `spec_version` change
- **THEN** a `chain-runtime-upgrade` alert is delivered, marked as a live-chain
  event, stating the previous and new live `spec_version` and reference block

#### Scenario: Governance threshold is surfaced

- **WHEN** a live `spec_version` change crosses a configured governance threshold
- **THEN** the chain-upgrade alert notes the threshold crossing

### Requirement: Notifications render with safe Telegram HTML

Outbound notifications SHALL be sent with Telegram HTML parse mode. All
dynamic values (SHAs, paths, commit subjects, provider text) SHALL be
HTML-escaped after scrubbing and before send. The renderer SHALL only emit tags
supported by the Telegram Bot API and SHALL produce a body already within the
configured message size limit with balanced tags; rendered HTML SHALL NOT be
truncated after rendering. On an HTTP 400 (rejected formatting), the notifier
SHALL retry once as plain text (the untagged structured text, never the raw
HTML source) so a rendering fault never suppresses an alert, and SHALL record
the fallback.

#### Scenario: Dynamic values are escaped

- **WHEN** a message containing user- or repo-derived text is rendered as HTML
- **THEN** every `&`, `<`, and `>` in dynamic values is escaped and the message
  is accepted by Telegram

#### Scenario: Formatting rejection falls back to plain text

- **WHEN** a send with HTML parse mode returns HTTP 400
- **THEN** the notifier retries the same event once as plain text and records the
  fallback, and the delivery is not lost to the formatting error
