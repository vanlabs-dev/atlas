## RENAMED Requirements

- FROM: `### Requirement: The judge returns an evidence-grounded structured verdict via a Hermes one-shot invocation`
- TO: `### Requirement: The judge returns an evidence-grounded structured verdict via a no-tools model call`
- FROM: `### Requirement: Model access reuses the Hermes subscription and introduces no new credential`
- TO: `### Requirement: Model access reuses the Claude subscription and introduces no new credential`

## MODIFIED Requirements

### Requirement: Diff content is untrusted and cannot steer the verdict or the agent

Diff content originates in arbitrary third-party subnet repositories and SHALL be treated as untrusted data. The judge prompt SHALL structurally fence the diff and the matched file names from its instructions, and SHALL constrain the model to the fixed output schema, so that text embedded in the diff (comments, strings, filenames) cannot change the judgment, alter the significance, or inject directives. The fence tag SHALL carry a random id generated per call, and every `<` in the fenced data SHALL be escaped as `&lt;`. The model invocation SHALL run locked down as the alert-plain-rewrite capability defines it (`claude -p` with no tools, no MCP servers, no settings files, no skills, no session persistence, one turn, outside the repository), so that untrusted diff text can neither drive agent tools nor persist. Code SHALL accept a verdict only when that call's `init` event lists no tools and no MCP servers; otherwise the judge SHALL record `unjudged`. The verdict text SHALL be recorded and later rendered as data only.

#### Scenario: Embedded directive in a diff is ignored
- **WHEN** a diff hunk contains text instructing the judge to report a specific significance or direction
- **THEN** the verdict reflects the code change on its merits and the embedded directive has no effect on significance, direction, or routing

#### Scenario: Diff text cannot close the fence
- **WHEN** a diff line or a file name contains a closing fence tag
- **THEN** the prompt carries exactly one closing tag and the data appears with `<` escaped inside the fence

#### Scenario: Judge invocation exposes no tools or memory
- **WHEN** the gate invokes the model to judge a candidate
- **THEN** the invocation enables no tools and no MCP servers and persists no session, so injected diff text cannot trigger tool use or persist

#### Scenario: A call that exposes a tool is discarded
- **WHEN** the `init` event of a judge call lists any tool or MCP server, or is missing
- **THEN** the verdict is not used and the candidate is recorded `unjudged`

### Requirement: The judge returns an evidence-grounded structured verdict via a no-tools model call

The gate SHALL submit the bounded diff, the matched file paths, and minimal subnet context to the model by invoking the local `claude` CLI in print mode and SHALL require a fixed-schema JSON verdict containing `what_changed`, `why_it_matters`, `significance` (one of `high`, `med`, `low`, `none`), `direction` (one of `emissions_up`, `emissions_down`, `reshuffle`, `neutral`, `unknown`), and `evidence` citing the specific changed lines or symbols the verdict rests on. The prompt SHALL define each significance level with an anchor the model must satisfy: `high` when the change alters who is paid or how much through the weight-setting or emission path in a way visible within an epoch; `med` when the change alters scoring inputs, parameters, or thresholds without changing the payout path; `low` when the change is a refactor, test, or tooling edit inside scoring files; `none` when cosmetic. The prompt SHALL instruct that a verdict which cannot name the payout-path line it rests on is at most `med`. The prompt SHALL instruct the model to emit only the JSON object, which the gate SHALL parse and validate against the schema. A verdict whose `evidence` is empty SHALL be coerced to `significance: none`. A response that fails schema validation SHALL be retried once and, on repeated failure, treated as `unjudged`.

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

### Requirement: Model access reuses the Claude subscription and introduces no new credential

Model access SHALL reuse the Claude subscription the local `claude` CLI is logged in with, the same login the runtime upgrade job uses; the gate SHALL NOT introduce a separate API key, metered credential, provider endpoint, or model id in repository code. The model is the CLI's default. Any error text from the invocation surfaced anywhere SHALL pass through the existing sensitive-output redaction before persistence or display.

#### Scenario: No new credential or hard-coded model id
- **WHEN** the repository is scanned for a model id or an API-key credential in the fleet judge code
- **THEN** none is present; auth is the `claude` CLI login

#### Scenario: Errors are never leaked
- **WHEN** a model invocation fails with an error containing sensitive text
- **THEN** the recorded error is redacted before it is stored or displayed
