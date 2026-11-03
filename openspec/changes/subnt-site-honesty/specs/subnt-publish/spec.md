# Spec Delta

## MODIFIED Requirements

### Requirement: Attention rows are ranked, capped, and named

The attention section SHALL list at most ten subnets ordered by the fleet
attention score descending, and SHALL omit any subnet whose attention
signal is unpaired emission opacity.

Each row's reason SHALL be derived from the recorded attention signal's
own components, not from its category alone. The dominant category is
near-constant across the fleet, so a fixed phrase per category renders a
list of identical lines that tells a reader nothing. A derived reason
SHALL distinguish rows by the size of the code-against-price gap and by
whether the repository has gone quiet. It SHALL NOT state which way the
price should move or which of code and price leads, in words or by sign,
and SHALL NOT state the numeric score, a direction-cue glyph, or a board
thesis sentence. An unrecognised category SHALL render as a named gap,
never as a raw token.

Rows that share a reason SHALL be grouped, and each group SHALL state its
reason once with its membership count, so that repetition is stated
rather than repeated and an exception is visible.

A row whose recorded on-chain name is absent SHALL name that gap and
SHALL NOT invent a name. When no row remains after the cap and the
opacity filter, the section SHALL name that gap.

#### Scenario: One category, two gap sizes

- **WHEN** two subnets share the dominant divergence category, one with a
  gap of 60 places and one with a gap of 15
- **THEN** their reasons read differently

#### Scenario: One category, two directions

- **WHEN** two subnets share the dominant attention category and differ
  only in the direction of the gap (+50 and -50, same quiet state)
- **THEN** their reasons are identical and neither says ahead, behind,
  faster, or priced ahead

#### Scenario: Rows sharing a reason are grouped

- **WHEN** several rows carry the same reason
- **THEN** they render as one group stating that reason once with its
  count

#### Scenario: No reason carries a score or a glyph

- **WHEN** any reason is rendered
- **THEN** it contains no numeric score and no direction-cue glyph

#### Scenario: Cap and order

- **WHEN** more than ten scored subnets qualify
- **THEN** the ten highest-scoring qualifying subnets render, in
  descending score order

#### Scenario: Unpaired opacity omitted

- **WHEN** a scored subnet's attention signal is unpaired emission
  opacity
- **THEN** it does not appear in the attention section

#### Scenario: Missing name

- **WHEN** a qualifying subnet has no recorded on-chain name
- **THEN** its row names the missing name and shows no substitute

#### Scenario: No rows remain

- **WHEN** no subnet qualifies
- **THEN** the section names the gap and lists no rows

## ADDED Requirements

### Requirement: The mining section describes the stored model

The mining section SHALL describe the head as the subnet Atlas ranks
first, and its notes SHALL state that the ranking is a model estimate for
one new independent miner at spot price, net of hardware cost at a band
Atlas does not publish. It SHALL NOT claim that hardware is not counted
or call the head the largest earnable pool.

#### Scenario: Model 3 notes

- **WHEN** a mining section is composed from a model-version-3 pass
- **THEN** its lead and notes name the rank-1 subnet as ranked first, say
  hardware cost is netted, and contain neither "not counted" nor
  "largest earnable pool"

#### Scenario: Band stays unpublished

- **WHEN** a mining section is composed
- **THEN** it names no budget band, rent figure, or hardware rung
