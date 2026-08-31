## MODIFIED Requirements

### Requirement: The judge returns an evidence-grounded structured verdict via a Hermes one-shot invocation

The gate SHALL submit the bounded diff, the matched file paths, and minimal subnet context to the model by invoking the local `hermes` one-shot CLI and SHALL require a fixed-schema JSON verdict containing `what_changed`, `why_it_matters`, `significance` (one of `high`, `med`, `low`, `none`), `direction` (one of `emissions_up`, `emissions_down`, `reshuffle`, `neutral`, `unknown`), and `evidence` citing the specific changed lines or symbols the verdict rests on. The prompt SHALL define each significance level with an anchor the model must satisfy: `high` when the change alters who is paid or how much through the weight-setting or emission path in a way visible within an epoch; `med` when the change alters scoring inputs, parameters, or thresholds without changing the payout path; `low` when the change is a refactor, test, or tooling edit inside scoring files; `none` when cosmetic. The prompt SHALL instruct that a verdict which cannot name the payout-path line it rests on is at most `med`. The prompt SHALL instruct Hermes to emit only the JSON object, which the gate SHALL parse and validate against the schema. A verdict whose `evidence` is empty SHALL be coerced to `significance: none`. A response that fails schema validation SHALL be retried once and, on repeated failure, treated as `unjudged`.

#### Scenario: Well-formed verdict is accepted
- **WHEN** the model returns schema-valid JSON with non-empty evidence
- **THEN** the verdict is stored and used to route the outcome

#### Scenario: Anchors are present in every prompt
- **WHEN** the gate builds a judge prompt
- **THEN** the prompt contains the four level definitions and the payout-path rule verbatim from configuration

#### Scenario: Ungrounded verdict cannot claim significance
- **WHEN** the model returns a verdict with empty `evidence`
- **THEN** `significance` is forced to `none` regardless of the model's stated significance

#### Scenario: Malformed response is retried then fails soft
- **WHEN** the model returns text that fails schema validation twice
- **THEN** the candidate is emitted as `unjudged`

### Requirement: The verdict gates the outcome, with a high-stakes path floor

The gate SHALL route each candidate by verdict into the fleet signal queue for the notifier to deliver according to the class tier: `high` and `med` SHALL be queued as econ-code events carrying the verdict (at the default briefing tier, `high` is listed with its verdict and `med` is counted); `low` SHALL be queued as a digest line; `none` SHALL be dropped from delivery. Every verdict, including `none`, SHALL be persisted in the verdict store. Independently, any candidate whose matched paths include a configured high-stakes pattern (`mechanism`, `set_weights`, `emission`) SHALL NOT be routed below the digest tier even when the verdict is `none` or `unjudged`, so it is never absent from the briefing's count.

#### Scenario: Material change pages
- **WHEN** a candidate's verdict is `high` or `med`
- **THEN** an econ-code event carrying the verdict is queued and the notifier delivers it at the class's configured tier

#### Scenario: Cosmetic change is dropped
- **WHEN** a candidate's verdict is `none` and no high-stakes path is touched
- **THEN** no event or digest line is queued and the drop is recorded in the verdict store

#### Scenario: High-stakes path cannot be silently dropped
- **WHEN** a candidate touches a `mechanism`, `set_weights`, or `emission` path and the verdict is `none` or `unjudged`
- **THEN** at least a digest line is queued for that candidate
