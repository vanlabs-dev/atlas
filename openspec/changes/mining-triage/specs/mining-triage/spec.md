## ADDED Requirements

### Requirement: Miner-accessible emission is computed from sourced protocol constants only

The mining triage screen SHALL compute each subnet's miner-accessible alpha
emission from the alpha **distributed to participants** per block
(`alpha_out`), multiplied by the protocol miner share and by
`(1 - miner_burn)`, where `miner_burn` is the fraction of miner incentive
withheld to owner or owner-associated hotkeys.

The screen SHALL NOT use the alpha-reserve injection (`alpha_in`) as the
base. That figure measures TAO flowing into the pool, not alpha flowing to
miners, and it is capped, with the difference appearing as excess TAO
emission. Ranking on it would rank pool inflow rather than income.

Because the participant distribution is a protocol constant per block and
does not vary by subnet, the miner-accessible **quantity** carries no
ranking information. The screen SHALL therefore rank on the TAO value of
that alpha and on how few participants share it: alpha price and
`(1 - miner_burn)` against the observed concentration. The screen SHALL NOT
present emission quantity as a differentiator between subnets.

The protocol miner share SHALL be sourced from the knowledge base or the
tracked subtensor repository and recorded with its citation; it SHALL NOT be
hardcoded without a recorded source. The screen SHALL treat the observed
emission as already carrying the subnet-share penalty that `MinerBurned`
applies to the price share, and SHALL apply the burn factor exactly once
more, as the distribution-time withholding from the miner leg.

Percentages SHALL be stored and rendered in the same unit they are sourced
in, with the unit carried in the column name. A value sourced as 0-100 SHALL
NOT be stored as a 0-1 fraction, or the reverse, without an explicit
conversion.

#### Scenario: Burn factor is applied once to the miner leg

- **WHEN** a subnet reports a participant alpha distribution and a nonzero
  miner burn
- **THEN** miner-accessible alpha is that distribution times the sourced
  miner share times `(1 - burn)`, and the burn is not applied a second time

#### Scenario: Pool inflow is not mistaken for miner income

- **WHEN** a subnet's alpha-reserve injection differs from its participant
  distribution
- **THEN** the miner-accessible figure is computed from the participant
  distribution, and the injection is recorded as pool context only

#### Scenario: Constant quantity is not presented as a differentiator

- **WHEN** every subnet reports the same participant alpha distribution
- **THEN** the ranking is driven by alpha price, burn, and concentration,
  and no subnet is ranked above another on emission quantity

#### Scenario: Unsourced protocol constant blocks the computation

- **WHEN** the protocol miner share has no recorded citation
- **THEN** the screen records no miner-accessible figure for any subnet and
  reports the missing source, rather than assuming a value

### Requirement: The cut ladder is ordered and every exclusion records its reason

The screen SHALL apply exclusions as an ordered ladder and SHALL record, for
every excluded subnet, the gate at which it left and the value that
triggered it. An excluded subnet SHALL remain retrievable with its reason;
exclusion SHALL NOT be implemented as omission.

The ladder SHALL begin with the emission gate. A gate-disabled subnet still
distributes alpha to its miners, because the participant distribution runs
regardless of the gate; what it loses is the TAO inflow backing that alpha,
so the alpha's price decays and TAO-denominated income tends to zero. The
recorded reason SHALL say that, and SHALL NOT claim the subnet pays nothing.
The gate rung is followed by an on-chain identity rung. A subnet whose
owner-written on-chain `subnet_name` is a placeholder, or which has no
on-chain identity entry at all, SHALL be excluded: the owner has declared
the slot is not a going concern, and no income figure makes it enterable.
The match SHALL be against the name's normalised first token, so
punctuation and trailing prose do not defeat it, and the placeholder
vocabulary SHALL be configuration rather than code. The recorded reason
SHALL quote the chain name. The identity source SHALL be the chain, never a
curated registry, which may carry a friendlier cached name for the same
netuid.

An identity map that cannot be read as a whole SHALL leave the rung inert
and SHALL be recorded as unread, distinct from a subnet with no entry. A
storage item that has been renamed or is unreachable returns an empty key
set indistinguishable from every subnet being unnamed, and must not empty
the board.

The identity rung is followed by
an operator-configured miner-burn ceiling above which the owner captures
substantially the whole miner pool, followed by an operator-configured
top-1 incentive-share ceiling above which the field is winner-take-all,
followed by feasibility verdicts that
make mining impossible, followed by a hardware floor above the configured
budget band.

The winner-take-all rung SHALL be evaluated on the top-1 share of the
incentive vector, NOT on the count of UIDs earning a nonzero amount. A
subnet may pay many UIDs while one of them takes substantially the whole
pool, and an earner-count test does not detect that. Where the incentive
vector was not read, the rung SHALL NOT cut: an unread field is not a
concentrated one.

#### Scenario: Gate-disabled subnet is cut with an accurate reason

- **WHEN** a subnet reports emission disabled
- **THEN** it is excluded at the gate rung with a reason naming unbacked
  alpha and a decaying price, not absent payment, and it remains
  retrievable from the store and the query surface as an excluded subnet

#### Scenario: Owner-abandoned subnet is cut on its chain name

- **WHEN** a subnet's on-chain `subnet_name` reduces to a configured
  placeholder token, or the subnet has no on-chain identity entry
- **THEN** it is excluded at the identity rung with a reason quoting the
  chain name, ahead of any burn, feasibility or hardware consideration, and
  it remains retrievable as an excluded subnet

#### Scenario: A real name that merely contains a placeholder word survives

- **WHEN** a subnet's on-chain name contains a placeholder word other than
  as its first token
- **THEN** it is not excluded at the identity rung

#### Scenario: Unreadable identity map cuts nothing

- **WHEN** the on-chain identity map enumerates empty or fails to read
- **THEN** every subnet records an unread identity state, the identity rung
  excludes no subnet, and the board is not emptied

#### Scenario: Burn ceiling cuts owner-captured subnets

- **WHEN** a subnet's miner burn is at or above the configured ceiling
- **THEN** it is excluded at the burn rung and is not ranked, because both
  the share penalty and the withholding leave a new miner nothing

#### Scenario: Winner-take-all field is cut on share, not on earner count

- **WHEN** a subnet's top-1 incentive share is at or above the configured
  ceiling, whatever its earner count
- **THEN** it is excluded at the winner-take-all rung with a reason
  carrying both the share and the earner count

#### Scenario: Unread incentive vector is not treated as concentrated

- **WHEN** a subnet's top-1 incentive share is unknown
- **THEN** the winner-take-all rung does not exclude it

### Requirement: Competition is read from the chain incentive distribution

The screen SHALL derive competition from the chain per-subnet incentive
vector, recording the count of UIDs earning nonzero incentive, the top-1
share, and the top-10 share. It SHALL NOT derive per-miner expected income
by dividing subnet emission by the registered UID count or by a provider's
active-miner headcount, because registered UIDs materially exceed earners
and reward is concentrated.

The headline income figure SHALL be an ENTRANT figure, not an incumbent
one. It SHALL be computed under an explicitly stated parity assumption: the
entrant joins the field and matches the existing earners, so the
miner-accessible pool is shared among the earner count plus one. The screen
SHALL label this as a model wherever the figure is shown, and SHALL also
report what a current earner actually receives, so a reader can see when the
two diverge and entry therefore means displacing an incumbent rather than
joining a field.

The screen SHALL NOT rank on incumbent income. Doing so orders the board by
concentration, placing the least enterable subnets at the top where they
read as the best opportunities.

Where concentration indicates that a small number of incumbents hold
substantially all reward, the screen SHALL also report the rank a new
entrant would occupy.

#### Scenario: Registered count is not used as a divisor

- **WHEN** a subnet reports 256 registered UIDs and 4 earning UIDs
- **THEN** the screen records 4 earners with the observed concentration and
  reports no average-per-registered-UID income figure

#### Scenario: Concentration is carried to the reader

- **WHEN** a subnet's top-10 share is at or near the whole reward
- **THEN** the board and the query surface present the displacement rank
  required to earn, not a per-miner average

#### Scenario: A single incumbent does not become the top recommendation

- **WHEN** one earner holds the whole reward on a subnet
- **THEN** the headline figure is the entrant share under the parity
  assumption, the incumbent's own income is shown alongside it, and the
  subnet is not ranked above a comparable subnet with a healthier field
  purely because its incumbent earns more

#### Scenario: The parity assumption is stated, not implied

- **WHEN** the board or a tool presents the headline income figure
- **THEN** the parity assumption is stated in the same view, identified as
  a model rather than an observation

### Requirement: No net figure is produced from an incomplete read

The screen SHALL NOT compute or present a net income figure for a subnet
when any input to it was unavailable, null, or failed validation. Such a
subnet SHALL be recorded with an explicit confidence marker naming the
missing leg, and its other observed fields SHALL still be stored.

A failure of the panel leg SHALL leave prior rows intact and render the
board from last-known data with its age shown. A failure of the chain leg
SHALL persist economics rows with competition fields null and no net figure.
A per-subnet failure SHALL NOT prevent other subnets in the same pass from
being recorded.

#### Scenario: Chain leg unavailable

- **WHEN** the chain read fails for a pass
- **THEN** economics rows are persisted with a chain-unavailable confidence
  marker, competition fields null, and no net income figure computed

#### Scenario: One subnet fails, the pass continues

- **WHEN** a single subnet's storage read is malformed
- **THEN** that subnet is marked unknown and every other subnet in the pass
  is recorded normally

### Requirement: Feasibility findings are evidence-cited, sha-gated, and never execute subnet code

The screen SHALL derive each subnet's mining feasibility from the existing
fleet code index and clones, recording a verdict from a closed set together
with the file and line that justifies it. It SHALL record the declared
hardware floor where the repository states one, the miner entrypoint path
where present, and whether the miner delegates to a hosted inference API.

A feasibility scan SHALL be keyed by netuid, identity epoch, and the scanned
commit, and SHALL be recomputed only when the scanned commit moves. The scan
SHALL NOT build, install, test, or execute subnet code.

An absent or unreadable signal SHALL produce an explicit unknown verdict.
An unknown verdict SHALL NOT be rendered or reported as feasible.

#### Scenario: Declared hardware floor is cited

- **WHEN** a subnet clone declares a hardware floor in its repository
- **THEN** the floor is recorded with the file and line it was read from,
  and that citation is returned with the finding

#### Scenario: Unscanned commit is not silently reused

- **WHEN** a slot's commit has moved since the last feasibility scan
- **THEN** the scan is recomputed for the new commit rather than serving the
  previous commit's verdict

#### Scenario: Missing evidence yields unknown, not feasible

- **WHEN** no hardware floor, entrypoint, or GPU signal can be read
- **THEN** the verdict is unknown and the subnet is never presented as
  feasible

### Requirement: The screen runs inside the existing fleet pass and is fail-isolated

The screen SHALL run inline within the existing scheduled fleet pass, after
the rotation-metrics pass, and SHALL NOT require a new scheduled unit, a new
network port, or a new credential. A failure anywhere in the screen SHALL be
recorded and SHALL NOT fail the enclosing pass or affect reconcile, signals,
or metrics.

All provider and chain access SHALL go through the live-data component, so
that every external call is subject to its existing validation, retry,
quota, and audit behaviour. The mining collector SHALL NOT open a network
connection directly.

#### Scenario: Screen failure does not fail the pass

- **WHEN** the mining screen raises during a fleet pass
- **THEN** the failure is recorded, the pass completes, and reconcile,
  signals, and metrics results are unaffected

#### Scenario: No direct network access from the collector

- **WHEN** the screen needs panel or chain data
- **THEN** it obtains it through the live-data component, and the call
  appears in the live-data audit record

### Requirement: Economics history is bounded and the board reports its own freshness

Recorded economics observations SHALL be pruned below a configured retention
horizon on each pass, so the store does not grow without bound. Feasibility
records, being keyed by scanned commit, SHALL NOT be pruned by time.

The board and the query surface SHALL each carry two distinct timestamps:
when the economics were observed and when the feasibility was last scanned.
A reader SHALL be able to tell which half of an answer is fresh, because
economics move every pass while feasibility only moves when a clone moves.

#### Scenario: Old observations are pruned

- **WHEN** a pass runs and observations older than the retention horizon
  exist
- **THEN** those observations are deleted and the current pass is recorded

#### Scenario: Both timestamps travel with the answer

- **WHEN** any subnet's data is returned by the board or a tool
- **THEN** the economics observation time and the feasibility scan time are
  both present and distinguishable

### Requirement: The screen ranks evidence and takes no action

The screen SHALL NOT hold, read, or derive a wallet key, SHALL NOT submit a
transaction of any kind, SHALL NOT register on a subnet, and SHALL NOT run
or deploy a miner. Its entire output is recorded observations, a ranking
with recorded reasons, and read-only presentations of both.

The ranking SHALL be presented as evidence for an operator decision. The
screen SHALL NOT act on its own output.

#### Scenario: No mutating capability exists

- **WHEN** the screen produces its highest-ranked subnet
- **THEN** no registration, transaction, deployment, or key access occurs,
  and the output is a recorded ranking only
