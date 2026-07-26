# econ-alert-intelligence Specification

## Purpose
Put a language-model materiality judgment between econ-path detection and the
operator's phone: when fleet-signals flags an incentive-code change, the gate
reads the actual diff from the local blobless clone (read-only, bounded, never
executing subnet code), asks the local Hermes CLI for an evidence-grounded
structured verdict, and routes the candidate by significance — page, digest, or
recorded drop — with a high-stakes path floor so mechanism/weights/emission
changes can never vanish silently. Diff text is untrusted end to end; verdicts
are cached by change content, budget- and timeout-bounded, fail soft as
`unjudged`, reuse the Hermes subscription (no new credential), and are
observable via `status`.

## Requirements

### Requirement: Econ candidates read a bounded diff from the local clone without executing subnet code

When econ-path detection identifies a change range as a candidate, the gate SHALL obtain the diff hunks for the matched econ files from the existing local blobless clone using read-only git (the established diff helper), and SHALL NOT check out, build, or execute any subnet code. The diff SHALL be bounded by a configured maximum size; when the range's aggregate diff exceeds the bound it SHALL be truncated and the candidate SHALL be flagged as a partial view rather than skipped.

#### Scenario: Diff is fetched read-only from the clone
- **WHEN** a range matches an econ path and a clone is available
- **THEN** the gate fetches the changed-line hunks for the matched files via read-only git against the local clone, without executing any repository code

#### Scenario: Oversized aggregate diff is truncated, not dropped
- **WHEN** the aggregate `prev_sha→new_sha` diff for the matched files exceeds the configured size bound
- **THEN** the diff is truncated to the bound and the candidate proceeds to judgment marked as a partial view

#### Scenario: Clone or diff unavailable degrades to unjudged
- **WHEN** the clone is missing or the diff cannot be read
- **THEN** the candidate is emitted as `unjudged` and is never silently dropped

### Requirement: The judge returns an evidence-grounded structured verdict via a Hermes one-shot invocation

The gate SHALL submit the bounded diff, the matched file paths, and minimal subnet context to the model by invoking the local `hermes` one-shot CLI and SHALL require a fixed-schema JSON verdict containing `what_changed`, `why_it_matters`, `significance` (one of `high`, `med`, `low`, `none`), `direction` (one of `emissions_up`, `emissions_down`, `reshuffle`, `neutral`, `unknown`), and `evidence` citing the specific changed lines or symbols the verdict rests on. The prompt SHALL instruct Hermes to emit only the JSON object, which the gate SHALL parse and validate against the schema. A verdict whose `evidence` is empty SHALL be coerced to `significance: none`. A response that fails schema validation SHALL be retried once and, on repeated failure, treated as `unjudged`.

#### Scenario: Well-formed verdict is accepted
- **WHEN** the model returns schema-valid JSON with non-empty evidence
- **THEN** the verdict is stored and used to gate the outcome

#### Scenario: Ungrounded verdict cannot claim significance
- **WHEN** the model returns a verdict with empty `evidence`
- **THEN** `significance` is forced to `none` regardless of the model's stated significance

#### Scenario: Malformed response is retried then fails soft
- **WHEN** the model returns text that fails schema validation twice
- **THEN** the candidate is emitted as `unjudged`

### Requirement: Diff content is untrusted and cannot steer the verdict or the agent

Diff content originates in arbitrary third-party subnet repositories and SHALL be treated as untrusted data. The judge prompt SHALL structurally fence the diff from its instructions and SHALL constrain the model to the fixed output schema, so that text embedded in the diff (comments, strings, filenames) cannot change the judgment, alter the significance, or inject directives. The Hermes one-shot invocation SHALL run locked down — with no toolsets enabled and no memory write — so that untrusted diff text can neither drive agent tools nor persist to Hermes memory. The verdict text SHALL be recorded and later rendered as data only.

#### Scenario: Embedded directive in a diff is ignored
- **WHEN** a diff hunk contains text instructing the judge to report a specific significance or direction
- **THEN** the verdict reflects the code change on its merits and the embedded directive has no effect on significance, direction, or routing

#### Scenario: Judge invocation exposes no tools or memory
- **WHEN** the gate invokes Hermes to judge a candidate
- **THEN** the invocation enables no toolsets and performs no memory write, so injected diff text cannot trigger tool use or persist

### Requirement: The verdict gates the outcome, with a high-stakes path floor

The gate SHALL route each candidate by verdict: `high` or `med` significance SHALL page as a full instant econ-code alert; `low` SHALL queue a digest line; `none` SHALL drop the candidate from alerting. Independently, any candidate whose matched paths include a configured high-stakes pattern (`mechanism`, `set_weights`, `emission`) SHALL NOT be routed below the digest tier even when the verdict is `none` or `unjudged`.

#### Scenario: Material change pages
- **WHEN** a candidate's verdict is `high` or `med`
- **THEN** a full instant econ-code alert is emitted carrying the verdict

#### Scenario: Cosmetic change is dropped
- **WHEN** a candidate's verdict is `none` and no high-stakes path is touched
- **THEN** no alert or digest line is emitted and the drop is recorded

#### Scenario: High-stakes path cannot be silently dropped
- **WHEN** a candidate touches a `mechanism`, `set_weights`, or `emission` path and the verdict is `none` or `unjudged`
- **THEN** at least a digest line is emitted for that candidate

### Requirement: Verdicts are persisted, cached, and auditable by change content

The gate SHALL persist every verdict — including drops and `unjudged` outcomes — in a store keyed by a content hash of `(prev_sha, new_sha, sorted matched econ files)`. A candidate whose content hash already has a stored verdict SHALL reuse it without calling the model, making re-runs idempotent. The store SHALL retain dropped and unjudged verdicts so that false negatives are reviewable.

#### Scenario: Re-run reuses the cached verdict
- **WHEN** a range with an already-judged content hash is processed again
- **THEN** the stored verdict is reused and no model call is made

#### Scenario: Dropped candidates remain reviewable
- **WHEN** a candidate is judged `none` and dropped
- **THEN** its verdict, evidence, and content hash are retained in the store

### Requirement: Model calls are bounded by budget and timeout and fail soft

Each model call SHALL enforce a configured timeout. The gate SHALL enforce a configured per-run and per-day cap on model calls. When a call times out, or the per-run or per-day cap is reached, remaining candidates SHALL be emitted as `unjudged` rather than blocking the reconcile/extract pass or being dropped. A model failure SHALL never count as a reconcile process error.

#### Scenario: Timeout ships unjudged
- **WHEN** a model call exceeds the configured timeout
- **THEN** the candidate is emitted as `unjudged` and the pass continues

#### Scenario: Daily cap degrades gracefully
- **WHEN** the per-day model-call cap has been reached
- **THEN** further candidates that miss the verdict cache are emitted as `unjudged` without further model calls

### Requirement: Model access reuses the Hermes subscription and introduces no new credential

Model access SHALL reuse the existing Hermes X OAuth subscription by invoking the local `hermes` CLI; the gate SHALL NOT introduce a separate API key, metered credential, provider endpoint, or model id in repository code. The model is selected by Hermes's own configuration, preserving the replaceability rule enforced by model-validation. Any error text from the invocation surfaced anywhere SHALL pass through the existing sensitive-output redaction before persistence or display.

#### Scenario: No new credential or hard-coded model id
- **WHEN** the repository is scanned for a model id or an API-key credential in the fleet judge code
- **THEN** none is present; the model is named only in Hermes configuration and auth is the Hermes subscription

#### Scenario: Errors are never leaked
- **WHEN** a Hermes invocation fails with an error containing sensitive text
- **THEN** the recorded error is redacted before it is stored or displayed

### Requirement: Gate activity is observable via status

The `status` command SHALL report gate counters for the reporting window: candidates seen, alerted, digested, dropped, unjudged, and model calls made against the configured budget.

#### Scenario: Status surfaces gate counters
- **WHEN** the operator runs `status`
- **THEN** the output includes candidate, alerted, digested, dropped, unjudged, and budget-usage counts
