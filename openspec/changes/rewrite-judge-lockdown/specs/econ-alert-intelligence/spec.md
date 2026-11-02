## MODIFIED Requirements

### Requirement: Diff content is untrusted and cannot steer the verdict or the agent

Diff content originates in arbitrary third-party subnet repositories and SHALL be treated as untrusted data. The judge prompt SHALL structurally fence the diff and the matched file names from its instructions, and SHALL constrain the model to the fixed output schema, so that text embedded in the diff (comments, strings, filenames) cannot change the judgment, alter the significance, or inject directives. The fence tag SHALL carry a random id generated per call, and every `<` in the fenced data SHALL be escaped as `&lt;`. The Hermes one-shot invocation SHALL run locked down: with a toolset the installed Hermes verifies as yielding no tools before the first call of the process, with project rules, context files and memory disabled, outside the repository, and with no memory write, so that untrusted diff text can neither drive agent tools nor persist to Hermes memory. When the toolset check fails, the judge SHALL make no call and SHALL return `unjudged`. The verdict text SHALL be recorded and later rendered as data only.

#### Scenario: Embedded directive in a diff is ignored
- **WHEN** a diff hunk contains text instructing the judge to report a specific significance or direction
- **THEN** the verdict reflects the code change on its merits and the embedded directive has no effect on significance, direction, or routing

#### Scenario: Diff text cannot close the fence
- **WHEN** a diff line or a file name contains a closing fence tag
- **THEN** the prompt carries exactly one closing tag and the data appears with `<` escaped inside the fence

#### Scenario: Judge invocation exposes no tools or memory
- **WHEN** the gate invokes Hermes to judge a candidate
- **THEN** the invocation enables no toolsets and performs no memory write, so injected diff text cannot trigger tool use or persist

#### Scenario: A toolset with tools stops the judge
- **WHEN** the configured toolset resolves to one or more tools in the installed Hermes
- **THEN** no Hermes call is made and every candidate is recorded `unjudged`
