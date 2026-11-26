## MODIFIED Requirements

### Requirement: Model access reuses the Claude subscription and introduces no new credential

Model access SHALL reuse the Claude subscription the local `claude` CLI is logged in with, the same login the runtime upgrade job uses; the gate SHALL NOT introduce a separate API key, metered credential or provider endpoint, and SHALL NOT name a model id in repository code. The model SHALL be passed as `--model` from `tools/claude-model.json`, the one model setting for every Atlas `claude -p` call, because `--restricted` and `--setting-sources ""` make the CLI ignore the settings files (operator decision 2026-11-27: Opus 5.5). Any error text from the invocation surfaced anywhere SHALL pass through the existing sensitive-output redaction before persistence or display.

#### Scenario: No new credential or hard-coded model id
- **WHEN** the repository is scanned for a model id or an API-key credential in the fleet judge code
- **THEN** none is present; auth is the `claude` CLI login and the model comes from `tools/claude-model.json`

#### Scenario: Errors are never leaked
- **WHEN** a model invocation fails with an error containing sensitive text
- **THEN** the recorded error is redacted before it is stored or displayed
