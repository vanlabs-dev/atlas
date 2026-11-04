## ADDED Requirements

### Requirement: No unvalidated mechanism claims in chat
A chat response SHALL NOT state how the Bittensor protocol works (a rule,
a default, a limit, a date, or which call does what) unless a
`knowledge_search` or live-tool result in the current session supports
it. Otherwise the response SHALL call a tool first or mark the claim "not
verified". The canonical voice text and the device `SOUL.md` SHALL carry
this rule.

#### Scenario: Mechanism question answered from the knowledge base
- **WHEN** a user asks how commit-reveal works
- **THEN** the response follows a `knowledge_search` call in the session,
  or marks its mechanism statements "not verified"
