# econ-alert-intelligence Specification

## Purpose
Put a language-model materiality judgment between econ-path detection and the
operator's phone: when fleet-signals flags an incentive-code change, the gate
reads the actual diff from the local blobless clone (read-only, bounded, never
executing subnet code), asks the local `claude` CLI (no tools) for an evidence-grounded
structured verdict, and routes the candidate by significance — page, digest, or
recorded drop — with a high-stakes path floor so mechanism/weights/emission
changes can never vanish silently. Diff text is untrusted end to end; verdicts
are cached by change content, budget- and timeout-bounded, fail soft as
`unjudged`, reuse the `claude` CLI login (no new credential), and are
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

### Requirement: Model access reuses the Claude subscription and introduces no new credential

Model access SHALL reuse the Claude subscription the local `claude` CLI is logged in with, the same login the runtime upgrade job uses; the gate SHALL NOT introduce a separate API key, metered credential, provider endpoint, or model id in repository code. The model is the CLI's default. Any error text from the invocation surfaced anywhere SHALL pass through the existing sensitive-output redaction before persistence or display.

#### Scenario: No new credential or hard-coded model id
- **WHEN** the repository is scanned for a model id or an API-key credential in the fleet judge code
- **THEN** none is present; auth is the `claude` CLI login

#### Scenario: Errors are never leaked
- **WHEN** a model invocation fails with an error containing sensitive text
- **THEN** the recorded error is redacted before it is stored or displayed

### Requirement: Gate activity is observable via status

The `status` command SHALL report gate counters for the reporting window: candidates seen, alerted, digested, dropped, unjudged, and model calls made against the configured budget.

#### Scenario: Status surfaces gate counters
- **WHEN** the operator runs `status`
- **THEN** the output includes candidate, alerted, digested, dropped, unjudged, and budget-usage counts
