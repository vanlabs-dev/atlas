# mining-triage Specification

## Purpose
Join what the fleet's clones say a subnet's code requires to what the chain
says it pays, and rank subnets by what a NEW INDEPENDENT MINER could earn.
Read-only throughout: it ranks evidence, holds no keys, and takes no action.
Every excluded subnet keeps the reason and the value that excluded it, so an
exclusion can be argued with rather than merely observed.

## Requirements

### Requirement: Miner-accessible emission is computed from sourced protocol constants only

The mining triage screen SHALL compute each subnet's miner-accessible alpha
from the chain, per mechanism, at one finalized block. The base SHALL be the
alpha **distributed to participants** per block (`SubnetAlphaOutEmission`),
read from the chain rather than assumed. The distribution follows the halving
curve applied to each subnet's own alpha issuance, so it is equal across
subnets only while every subnet sits below the same issuance step.

The miner share SHALL be `0.5 x (1 - owner_cut)`, where `owner_cut` is the
chain `SubnetOwnerCut` (or its runtime default when unset) and is zero for a
subnet whose `OwnerCutEnabled` is false. The 50/50 split between incentive
and dividends SHALL be recorded with its source citation. The screen SHALL
NOT use a hand-set miner share. If the split's citation is missing, the
screen SHALL record no miner-accessible figure.

A subnet with more than one mechanism SHALL have its miner pool divided
across mechanisms by the chain `MechanismEmissionSplit`, or by an even split
when that item is unset. No mechanism SHALL be credited with another
mechanism's share.

The screen SHALL NOT use the alpha-reserve injection (`alpha_in`) as the
base. That figure measures TAO flowing into the pool, not alpha flowing to
miners.

Owner capture SHALL be removed by excluding owner-controlled UIDs from each
mechanism's incentive distribution, not by a subnet-wide `(1 - burn)`
factor. Owner-controlled UIDs are the UIDs held by the subnet's owner
hotkey and by every hotkey owned by the subnet owner's coldkey, as the chain
defines the burned set. The removed share, weighted by each mechanism's
split, SHALL reconcile with the chain `MinerBurned` within a configured
tolerance. A subnet that does not reconcile SHALL carry a confidence marker
naming the failure and SHALL have no net figure.

Where the miner-accessible quantity is equal across subnets, the screen
SHALL rank on the TAO value of that alpha and on how few independent miners
share it, and SHALL NOT present emission quantity as a differentiator.

Percentages SHALL be stored and rendered in the same unit they are sourced
in, with the unit carried in the column name. A value sourced as 0-1 SHALL
NOT be stored as 0-100, or the reverse, without an explicit conversion.

#### Scenario: Burn factor is applied once to the miner leg

- **WHEN** a subnet reports a nonzero `MinerBurned`
- **THEN** the owner capture is removed once, by excluding the owner UIDs'
  share of each mechanism, and no additional `(1 - burn)` factor is applied
  to the independent pool

#### Scenario: Constant quantity is not presented as a differentiator

- **WHEN** every subnet reports the same participant alpha distribution
- **THEN** the ranking is driven by alpha price, owner capture, and
  concentration, and no subnet is ranked above another on emission quantity

#### Scenario: Unsourced protocol constant blocks the computation

- **WHEN** the incentive/dividend split has no recorded citation
- **THEN** the screen records no miner-accessible figure for any subnet and
  reports the missing source, rather than assuming a value

#### Scenario: A second mechanism takes most of the pool

- **WHEN** a subnet runs two mechanisms with an emission split of 2% and 98%
- **THEN** mechanism 0 is credited with 2% of the miner pool and
  mechanism 1 with 98%, and neither is credited with the whole pool

#### Scenario: Owner UIDs are removed from the field

- **WHEN** an owner-coldkey hotkey holds a UID with 49.77% of a mechanism's
  incentive
- **THEN** that UID is excluded from the earner count, the top-1 share, the
  parity divisor and the incumbent figure, and its share is not paid to any
  independent miner

#### Scenario: Owner removal reconciles with MinerBurned

- **WHEN** the owner-UID share, weighted by mechanism split, differs from
  chain `MinerBurned` by more than the tolerance
- **THEN** the subnet is recorded with a reconciliation-failed confidence
  marker and no net figure

#### Scenario: Pool inflow is not mistaken for miner income

- **WHEN** a subnet's alpha-reserve injection differs from its participant
  distribution
- **THEN** the miner-accessible figure is computed from the participant
  distribution, and the injection is recorded as pool context only

#### Scenario: A halved subnet is not credited with the full rate

- **WHEN** a subnet's alpha issuance has crossed a halving step and its
  participant distribution is 0.5 alpha per block
- **THEN** its miner pool is computed from 0.5, not from 1.0

#### Scenario: Owner cut disabled for a subnet

- **WHEN** a subnet's `OwnerCutEnabled` is false
- **THEN** its miner share is 0.5 of the participant distribution

### Requirement: The cut ladder is ordered and every exclusion records its reason

The screen SHALL apply exclusions as an ordered ladder and SHALL record, for
every excluded subnet, the rung at which it left and the value that
triggered it. An excluded subnet SHALL remain retrievable with its reason;
exclusion SHALL NOT be implemented as omission.

The ladder SHALL begin with the **pool-side emission switch**, read from
chain `SubnetEmissionEnabled` at the same block as every other input. It
SHALL be named as a switch, not as the emission gate. A subnet with the
switch off still distributes alpha to its miners; what it loses is the TAO
inflow backing that alpha, so the price decays and TAO income tends to zero.
The recorded reason SHALL say that, SHALL NOT claim the subnet pays nothing,
and SHALL NOT attribute the exclusion to demand or to the bar. The board
SHALL carry the block its switch states were read at.

The switch rung is followed by the **identity** rung. A subnet whose
on-chain `subnet_name` reduces to a configured placeholder first token, or
which has no identity entry, SHALL be excluded with a reason quoting the
chain name. The identity source SHALL be the chain, never a curated
registry. An identity map that enumerates empty or fails to read SHALL leave
the rung inert. A single subnet whose identity entry exists but fails to
decode SHALL be recorded as unread for that subnet and SHALL NOT be cut as
unnamed.

The identity rung is followed by the **owner-capture** rung: a subnet whose
chain `MinerBurned` is at or above the configured ceiling is excluded.

The owner-capture rung is followed by the **no-independent-earner** rung. It
excludes a subnet on which no UID outside the owner set earns incentive in
any mechanism, with a reason saying the field has no paying independent
miner.

The no-independent-earner rung is followed by the **winner-take-all** rung.
It SHALL be evaluated per mechanism on the top-1 share of the incentive paid
to **independent** miners, after owner UIDs are removed. A mechanism is
winner-take-all when that share is at or above the configured ceiling. A
subnet SHALL be excluded at this rung only when every mechanism with a
nonzero emission split is winner-take-all or empty. The reason SHALL carry,
for each such mechanism, the independent top-1 share and the independent
earner count. Where a mechanism's incentive vector was not read, the rung
SHALL NOT cut on it.

The winner-take-all rung is followed by the **feasibility** rung. It SHALL
cut only on positive evidence that mining is impossible. An `unknown`
verdict SHALL NOT cut. The feasibility rung is followed by a hardware floor
above the configured budget band.

#### Scenario: Gate-disabled subnet is cut with an accurate reason

- **WHEN** chain `SubnetEmissionEnabled` is false for a subnet
- **THEN** it is excluded at the switch rung with a reason naming the switch,
  unbacked alpha and a decaying price, and it remains retrievable as an
  excluded subnet

#### Scenario: A switch flip is attributable on the board

- **WHEN** the ranked count changes between passes because the switch
  changed for one or more subnets
- **THEN** the board carries the block its switch states were read at, and
  that block is the same block as the economics

#### Scenario: Owner-abandoned subnet is cut on its chain name

- **WHEN** a subnet's on-chain `subnet_name` reduces to a configured
  placeholder token, or the subnet has no on-chain identity entry
- **THEN** it is excluded at the identity rung with a reason quoting the
  chain name

#### Scenario: A real name that merely contains a placeholder word survives

- **WHEN** a subnet's on-chain name contains a placeholder word other than
  as its first token
- **THEN** it is not excluded at the identity rung

#### Scenario: Unreadable identity map cuts nothing

- **WHEN** the on-chain identity map enumerates empty or fails to read
- **THEN** every subnet records an unread identity state and the identity
  rung excludes no subnet

#### Scenario: One undecodable identity is unread, not unnamed

- **WHEN** a subnet's identity entry exists but fails to decode
- **THEN** that subnet records an unread identity state and is not excluded
  at the identity rung

#### Scenario: Burn ceiling cuts owner-captured subnets

- **WHEN** a subnet's chain `MinerBurned` is at or above the configured
  ceiling
- **THEN** it is excluded at the owner-capture rung

#### Scenario: Only the owner earns

- **WHEN** every UID earning incentive on a subnet belongs to the owner set,
  or no UID earns at all
- **THEN** it is excluded at the no-independent-earner rung and is never
  ranked on a pool divided by one

#### Scenario: Winner-take-all field is cut on share, not on earner count

- **WHEN** every mechanism with a nonzero split has an independent top-1
  share at or above the configured ceiling, whatever its earner count
- **THEN** the subnet is excluded at the winner-take-all rung with a reason
  carrying each mechanism's independent share and earner count

#### Scenario: Owner share hides a winner-take-all field

- **WHEN** the owner UID holds 49.77% of a mechanism and one independent UID
  holds 99.56% of the rest
- **THEN** the mechanism is winner-take-all, and the subnet is excluded when
  it has no other surviving mechanism

#### Scenario: One open mechanism keeps the subnet ranked

- **WHEN** a subnet has one winner-take-all mechanism and one mechanism
  below the ceiling with a nonzero split
- **THEN** the subnet is ranked on the surviving mechanism, and the board
  names that mechanism

#### Scenario: Unread incentive vector is not treated as concentrated

- **WHEN** a mechanism's incentive vector is unknown
- **THEN** the winner-take-all rung does not exclude on that mechanism

#### Scenario: Unknown feasibility does not cut

- **WHEN** a subnet's feasibility verdict is unknown
- **THEN** it is not excluded at the feasibility rung and is shown as
  unverified

### Requirement: Competition is read from the chain incentive distribution

The screen SHALL derive competition per mechanism from the chain incentive
vector for that mechanism, after owner UIDs are removed. It SHALL record the
independent earner count, the independent top-1 share and the independent
top-10 share for each mechanism. It SHALL NOT derive per-miner income by
dividing emission by the registered UID count or by a provider's
active-miner headcount.

The headline income figure SHALL be an ENTRANT figure computed under an
explicitly stated parity assumption. The entrant joins one mechanism and
matches its independent earners. The mechanism's independent pool, meaning
its miner pool minus the owner share, is shared among the independent
earner count plus one. The subnet's headline SHALL be the highest entrant
figure among its surviving mechanisms, and the view SHALL name that
mechanism. The screen SHALL label the figure as a model wherever it is
shown, and SHALL also report what a current independent earner receives
(the median), so a reader can see when entry means displacing an incumbent
rather than joining a field.

The screen SHALL NOT rank on incumbent income. It SHALL NOT produce an
entrant figure for a mechanism with no independent earner.

The screen SHALL carry, as context and not as a ranking input:
- the registration burn in TAO at the read block
- the immunity period in blocks
- whether the subnet's UIDs are full, so that entry means deregistering an
  existing UID

#### Scenario: Registered count is not used as a divisor

- **WHEN** a subnet reports 256 registered UIDs and 4 independent earners
- **THEN** the screen records 4 earners and reports no
  average-per-registered-UID figure

#### Scenario: Concentration is carried to the reader

- **WHEN** a mechanism's independent top-10 share is at or near the whole
  independent reward
- **THEN** the board and the query surface present the independent earner
  count and top-1 share with the entrant figure, not a per-miner average

#### Scenario: Owner UID does not inflate the parity divisor

- **WHEN** a mechanism has 4 earning UIDs, one of them the owner's
- **THEN** the entrant figure divides the independent pool by 4, not by 5

#### Scenario: A single incumbent does not become the top recommendation

- **WHEN** one independent earner holds the whole independent reward
- **THEN** the headline is the entrant share under the parity assumption,
  the incumbent's income is shown alongside, and the subnet is not ranked
  above a healthier field because its incumbent earns more

#### Scenario: The parity assumption is stated, not implied

- **WHEN** the board or a tool presents the headline income figure
- **THEN** the parity assumption is stated in the same view, identified as
  a model

#### Scenario: Entry into a full subnet is visible

- **WHEN** a subnet's registered UIDs equal its maximum
- **THEN** the view marks entry as requiring deregistration and carries the
  immunity period and registration burn

### Requirement: No net figure is produced from an incomplete read

The screen SHALL NOT compute or present a net income figure for a subnet
when any input to it was unavailable, null, failed decoding, or failed
owner reconciliation. Such a subnet SHALL carry an explicit confidence
marker naming what was missing, and its other observed fields SHALL still be
stored. An unknown exit haircut SHALL be recorded as unknown and SHALL block
the net figure. It SHALL NOT be treated as zero.

Every economics input comes from one chain read at one finalized block. A
failure of that read as a whole SHALL write no economics rows and SHALL
leave prior rows intact. The board SHALL then keep presenting the last
complete pass with its age. A malformed value for one subnet SHALL mark that
subnet alone and SHALL NOT abort the pass. A pass SHALL either commit all of
its rows or none of them.

#### Scenario: Chain leg unavailable

- **WHEN** the chain read fails for a pass
- **THEN** no economics rows are written, the previous complete pass stays
  current, and the board shows its age

#### Scenario: One subnet fails, the pass continues

- **WHEN** a single subnet's storage value is malformed
- **THEN** that subnet is marked with a confidence marker naming the input,
  and every other subnet in the pass is recorded normally

#### Scenario: A mid-pass fault leaves no partial pass

- **WHEN** the economics stage raises after some rows were prepared
- **THEN** none of that pass's rows are committed

### Requirement: Feasibility findings are evidence-cited, sha-gated, and never execute subnet code

The screen SHALL derive each subnet's mining feasibility from the existing
fleet code index, recording a verdict from a closed set together with the
file and line that justifies it. It SHALL record the declared miner hardware
floor where the repository states one, the miner entrypoint path where
present, and whether the miner delegates to a hosted inference API.

A miner entrypoint SHALL be recognised across the languages the index
holds. This includes a runnable miner module, a miner package directory, and
a miner command directory. A file SHALL NOT count as an entrypoint when it
sits under validator, API route, database migration, test or registration
script paths.

A `min_compute` declaration that is the unedited subnet template SHALL NOT
count as a hardware declaration, and SHALL be recorded as template
evidence.

An absent signal SHALL produce `unknown`. A verdict of `closed` or `stub`
SHALL require positive evidence cited by path and line, and SHALL NOT be
inferred from the absence of an entrypoint or from a file count. An
`unknown` verdict SHALL NOT be rendered or reported as feasible, and SHALL
NOT cut.

A scan SHALL be keyed by netuid, identity epoch, and the commit that was
actually indexed. It SHALL be recomputed when that commit moves or when the
scanner logic changes. A slot whose index is behind its clone SHALL NOT be
scanned until the index catches up. The scan SHALL NOT build, install,
test, or execute subnet code.

A verdict SHALL apply to a subnet only while it matches that slot's current
epoch and indexed commit and the slot is active. Any other verdict SHALL be
reported as stale or unscanned.

#### Scenario: Declared hardware floor is cited

- **WHEN** a subnet clone declares a miner hardware floor
- **THEN** the floor is recorded with the file and line of the miner section
  it was read from

#### Scenario: A Go or package-style miner is recognised

- **WHEN** a clone has `cmd/miner/main.go` or a `miner/` package with a
  runnable module, and no `miner.py`
- **THEN** an entrypoint is recorded and the verdict is not `closed`

#### Scenario: Validator code is not a miner entrypoint

- **WHEN** the only file named like a miner sits under a validator, API
  route, migration or test path
- **THEN** it is not recorded as the entrypoint

#### Scenario: Missing evidence yields unknown, not feasible

- **WHEN** no entrypoint, hardware floor, or GPU signal can be read
- **THEN** the verdict is unknown, the subnet is never presented as
  feasible, and it is not cut

#### Scenario: Template min_compute is not a declaration

- **WHEN** a clone's `min_compute.yml` is the unedited subnet template
- **THEN** no hardware floor is recorded from it and no GPU requirement is
  inferred from it

#### Scenario: Unscanned commit is not silently reused

- **WHEN** a slot's indexed commit has moved since the last scan
- **THEN** the scan is recomputed for the new commit rather than serving the
  previous verdict

#### Scenario: A re-pointed slot does not inherit the old verdict

- **WHEN** a netuid is re-pointed to a new repository whose clone has not
  been indexed
- **THEN** the previous repository's verdict does not apply and the subnet
  is reported as unscanned

### Requirement: The screen runs inside the existing fleet pass and is fail-isolated

The screen SHALL run inline within the existing scheduled fleet pass, after
the rotation-metrics pass, in the order economics, feasibility,
classification. It SHALL NOT require a new scheduled unit, a new network
port, or a new credential. A failure anywhere in the screen SHALL be
recorded and SHALL NOT fail the enclosing pass or affect reconcile, signals,
or metrics. A failure in one stage SHALL NOT leave a later stage's output
describing a pass that did not complete.

All chain access SHALL go through the live-data component, so every read is
subject to its key-derivation self-test, fail-closed decoding, and audit
record. The mining collector SHALL NOT open a network connection directly.
The screen SHALL NOT depend on a third-party provider panel.

#### Scenario: Screen failure does not fail the pass

- **WHEN** the mining screen raises during a fleet pass
- **THEN** the failure is recorded, the pass completes, and reconcile,
  signals, and metrics results are unaffected

#### Scenario: No direct network access from the collector

- **WHEN** the screen needs chain data
- **THEN** it obtains it through the live-data component, and the read
  appears in the live-data audit record

#### Scenario: Economics fail, classification does not run on stale rows

- **WHEN** the economics stage fails in a pass
- **THEN** classification does not overwrite the stored result of the last
  complete pass

### Requirement: Economics history is bounded and the board reports its own freshness

Economics observations SHALL be pruned below a configured retention
horizon on each pass. Feasibility records SHALL be pruned when superseded,
keeping only the verdict for each slot's current epoch and indexed commit.

The board and the query surface SHALL carry two distinct timestamps:
- when the economics were observed, with the block they were read at
- the most recent scan time among the feasibility verdicts actually joined,
  which is not the time the scanner last ran

The board SHALL state the age of its economics, and SHALL warn visibly when
that age exceeds a configured bound.

#### Scenario: Old observations are pruned

- **WHEN** a pass runs and observations older than the retention horizon
  exist
- **THEN** those observations are deleted and the current pass is recorded

#### Scenario: Superseded verdicts are pruned

- **WHEN** a slot is rescanned at a new commit
- **THEN** the verdict for the previous commit is removed

#### Scenario: Both timestamps travel with the answer

- **WHEN** any subnet's data is returned by the board or a tool
- **THEN** the economics observation time, its block, and the feasibility
  scan time are all present and distinguishable

#### Scenario: A stale board says so

- **WHEN** the last complete economics pass is older than the configured
  bound
- **THEN** the board shows a visible staleness warning with the age

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

### Requirement: The ranking is decided once per pass and every consumer reads it

After feasibility, each pass SHALL run the cut ladder once and SHALL store
the result against that pass's economics rows. For every subnet it stores
exactly one of:
- the cut rung and detail
- the rank and the mechanism the rank is based on
- an unrated marker naming the missing input, for a subnet that survives the
  ladder but has no figure

An unrated subnet SHALL NOT be ranked below rated subnets as if it had a
low figure. It SHALL be counted and listed separately.
The board page, the query surface, the pulse briefing and the subnt
publisher SHALL read the stored result. None of them SHALL re-derive cut
state or re-sort raw rows. Consumer tests SHALL obtain their fixtures from
the same writer production uses.

#### Scenario: Briefing and board agree

- **WHEN** a pass stores a result with a given ranked count, cut count and
  head
- **THEN** the board, the pulse briefing and the subnt publisher report
  exactly those counts and that head for that pass

#### Scenario: A cut subnet is never published as the head

- **WHEN** the highest raw figure belongs to a subnet cut as winner-take-all
- **THEN** no consumer names it as the board head

#### Scenario: Cut state is in the store

- **WHEN** a pass completes
- **THEN** every economics row of that pass carries exactly one of a cut
  rung and detail, a rank, or an unrated marker

#### Scenario: A subnet without a figure is unrated, not last

- **WHEN** a subnet survives the ladder but its owner reconciliation failed
- **THEN** it is stored as unrated with the reason, counted apart from the
  ranked subnets, and never placed at the bottom of the ranking
