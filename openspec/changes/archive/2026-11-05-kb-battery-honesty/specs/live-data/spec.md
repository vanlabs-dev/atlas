## ADDED Requirements

### Requirement: Corpus-stated network values are read and watched
Every network-wide chain value the corpus states as live SHALL be a
declared chain read with its metadata default pinned for the probe, SHALL
be part of `read-knobs`, and SHALL be in the chain-parameter watch, so a
root change records a transition and pages through the
`chain-parameter-change` class. The values are `MaturityRate`,
`UnlockRate`, `StakeThreshold`, `PendingChildKeyCooldown`,
`MaxChildkeyTake`, `MinChildkeyTake`, `TxChildkeyTakeRateLimit`, `CKBurn`
and `CommitRevealWeightsVersion`, in addition to the items already
watched.

#### Scenario: A root write changes a corpus-stated value
- **WHEN** root changes `MaturityRate` on chain
- **THEN** the next watch pass records a transition and the instant
  `chain-parameter-change` alert names the item, its old and new value,
  and the block

### Requirement: Watched chain parameters readable by the agent
`atlas-live` SHALL provide a read-only `live_chain_params` tool that
returns, for every network-wide watched parameter, the latest stored value
with its provenance, read time and block, or `not-read-yet`. It SHALL make
no provider call, and SHALL return a structured `unavailable` error when
no watch is configured. Per-subnet values stay with `live_hyperparams`.

#### Scenario: Agent asks for the conviction rate
- **WHEN** the agent calls `live_chain_params`
- **THEN** the result includes `MaturityRate` with its stored value, block
  and provenance, and no provider was called
