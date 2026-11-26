## MODIFIED Requirements

### Requirement: Rewrites are cached by content and reuse the Claude subscription

The rewrite SHALL be cached by a hash of the model input and the prompt
version, so a repeat of the same content makes no second call. The pass SHALL
use the local `claude` CLI with the subscription it is logged in with, the
same login the runtime upgrade job uses. It SHALL introduce no API key or
provider endpoint into Atlas code or configuration, and SHALL name no model
id in code. The model SHALL be passed as `--model` from
`tools/claude-model.json`, because the locked-down call ignores the settings
files (operator decision 2026-11-27: Opus 5.5). A `rewrite.enabled` switch
of `false` SHALL restore template-only sending with no other change.

#### Scenario: Same content, one call

- **WHEN** two events with identical rewrite input are processed
- **THEN** the second uses the cached result and makes no model call

#### Scenario: Rollback is one switch

- **WHEN** `rewrite.enabled` is set to `false`
- **THEN** the next scan sends template alerts and makes no model call

#### Scenario: Model is pinned

- **WHEN** a rewrite call is built
- **THEN** its argv carries `--model` with the value of
  `tools/claude-model.json`
