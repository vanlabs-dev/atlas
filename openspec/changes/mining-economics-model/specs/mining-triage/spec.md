## MODIFIED Requirements

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

The winner-take-all rung is followed by the **prune-risk** rung. A subnet
whose registered UIDs equal its maximum and whose immunity period is below
a configured number of blocks SHALL be excluded, with a reason carrying the
immunity period and the configured floor: a new UID there can be pruned
before it is ever scored. An unread fullness or immunity period SHALL NOT
cut.

The prune-risk rung is followed by the **feasibility** rung. It SHALL
cut only on positive evidence that mining is impossible. An `unknown`
verdict SHALL NOT cut. The feasibility rung is followed by the **hardware**
rung, which cuts a subnet whose required hardware band is above the
configured budget band.

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

#### Scenario: A full subnet with a short immunity period is cut

- **WHEN** a subnet's registered UIDs equal its maximum and its immunity
  period is 1 block against a configured floor of 720
- **THEN** it is excluded at the prune-risk rung with a reason carrying 1
  and 720

#### Scenario: An open subnet with a short immunity period survives

- **WHEN** a subnet has a free UID slot and an immunity period below the
  floor
- **THEN** it is not excluded at the prune-risk rung

#### Scenario: Unknown immunity does not cut

- **WHEN** a subnet's immunity period or fullness was not read
- **THEN** it is not excluded at the prune-risk rung

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
active-miner headcount. Registered UIDs that earn nothing SHALL NOT be a
divisor and SHALL NOT cut. The screen SHALL NOT claim whether such a UID is
active or idle, and SHALL show them only as context ("N earning of M
registered").

The headline income figure SHALL be an ENTRANT figure: the LOWER of two
figures for one mechanism.
- The parity share: the mechanism's independent pool, meaning its miner pool
  minus the owner share, divided by the independent earner count plus one.
- The 25th-percentile independent earner's income in that mechanism.

The subnet's headline SHALL be the highest entrant figure among its
surviving mechanisms, and the view SHALL name that mechanism. The screen
SHALL label the figure as a model wherever it is shown. It SHALL also report
the parity share, the 25th-percentile earner and the median independent
earner. A reader can then see when entry means displacing an incumbent
rather than joining a field.

The screen SHALL NOT rank on the median or top incumbent's income. Earner
income enters the headline only as a cap below the parity share. It SHALL
NOT produce an entrant figure for a mechanism with no independent earner.

The screen SHALL carry, as context and not as a ranking input:
- the registration burn in TAO at the read block
- the immunity period in blocks
- whether the subnet's UIDs are full, so that entry means deregistering an
  existing UID
- the number of registered UIDs and how many of them earn
- the miner-activity facts and the consensus mode

#### Scenario: Registered count is not used as a divisor

- **WHEN** a subnet reports 256 registered UIDs and 4 independent earners
- **THEN** the screen records 4 earners and reports no
  average-per-registered-UID figure

#### Scenario: Zero-earning UIDs are context, not a divisor

- **WHEN** a full subnet has 3 independent earners among 255 non-owner UIDs
- **THEN** the entrant figure is computed from the 3 earners alone, the
  subnet is not cut or scaled for the other 252 UIDs, the view shows "3
  earning of 255 registered", and no view calls those 252 UIDs idle or
  active

#### Scenario: A long tail of tiny earners caps the headline

- **WHEN** a mechanism's parity share is 147.6 alpha/day and its
  25th-percentile independent earner receives 0.07 alpha/day
- **THEN** the entrant figure is 0.07 alpha/day, and the parity share and
  median earner are reported beside it

#### Scenario: A few strong earners keep the parity figure

- **WHEN** a mechanism's 25th-percentile independent earner receives more
  than its parity share
- **THEN** the entrant figure is the parity share

#### Scenario: Concentration is carried to the reader

- **WHEN** a mechanism's independent top-10 share is at or near the whole
  independent reward
- **THEN** the board and the query surface present the independent earner
  count and top-1 share with the entrant figure, not a per-miner average

#### Scenario: Owner UID does not inflate the parity divisor

- **WHEN** a mechanism has 4 earning UIDs, one of them the owner's
- **THEN** the parity share divides the independent pool by 4, not by 5, and
  the owner UID is not in the percentile set

#### Scenario: A single incumbent does not become the top recommendation

- **WHEN** one independent earner holds the whole independent reward
- **THEN** the headline is at most the parity share, the incumbent's income
  is shown alongside, and the subnet is not ranked above a healthier field
  because its incumbent earns more

#### Scenario: The parity assumption is stated, not implied

- **WHEN** the board or a tool presents the headline income figure
- **THEN** the model (lower of parity share and 25th-percentile earner) is
  stated in the same view, identified as a model

#### Scenario: Entry into a full subnet is visible

- **WHEN** a subnet's registered UIDs equal its maximum
- **THEN** the view marks entry as requiring deregistration and carries the
  immunity period and registration burn

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

GPU evidence SHALL be read from every indexed file of the miner subtree,
the entrypoint and the `min_compute` declaration, not from one file. The
miner subtree is every path with a miner-named component outside validator,
test, docs, example and vendored paths. A code-level GPU token SHALL yield
`needs-gpu`, also when no miner entrypoint is recognised. A bare mention of
a GPU, vendor or card name SHALL be recorded as mention evidence and SHALL
NOT change the verdict.

A `min_compute` declaration that is the unedited subnet template SHALL NOT
count as a hardware declaration, and SHALL be recorded as template
evidence.

An absent signal SHALL produce `unknown`. A verdict of `closed` or `stub`
SHALL require positive evidence cited by path and line, and SHALL NOT be
inferred from the absence of an entrypoint or from a file count. An
`unknown` verdict SHALL NOT be rendered or reported as feasible, and SHALL
NOT cut. A `possible` verdict SHALL be rendered as "no GPU code found",
with the number of files that mention a GPU where any do, and never as a
statement that the miner runs on a CPU.

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

#### Scenario: GPU code outside the entrypoint is found

- **WHEN** a miner's entrypoint has no GPU token but another file in its
  miner subtree calls `torch.cuda`
- **THEN** the verdict is `needs-gpu`, citing that file and line

#### Scenario: GPU code without a recognised entrypoint

- **WHEN** no miner entrypoint is recognised but a miner-subtree file calls
  `torch.cuda`
- **THEN** the verdict is `needs-gpu`, citing that file and line

#### Scenario: A bare GPU mention does not make a GPU miner

- **WHEN** the only GPU evidence in a miner subtree is the word "GPU" in a
  comment or README
- **THEN** it is recorded as mention evidence, the verdict stays as the
  other evidence makes it, and a `possible` verdict is shown as "no GPU
  code found; GPU mentioned in 1 file(s)"

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

## ADDED Requirements

### Requirement: Hardware is costed per subnet against a chosen budget band

Each surviving subnet SHALL be assigned the hardware band its evidence
requires:
- no GPU code found: the CPU band, marked as assumed
- a declared VRAM floor: the smallest band that covers it
- GPU evidence without a declared floor: the smallest GPU band, marked as
  assumed
- unknown or unscanned: the budget band, marked as assumed

Net income SHALL be gross minus that band's hand-set rent. The rent SHALL
carry its source and date in configuration. With no budget band chosen, no
subnet SHALL be ranked.

#### Scenario: Undeclared GPU need is costed at the smallest GPU band

- **WHEN** a subnet's verdict is `needs-gpu` with no declared VRAM and the
  budget band is the consumer band
- **THEN** its required band is the consumer band, marked as assumed, it is
  netted at that band's rent, and it is not cut at the hardware rung

#### Scenario: A declared floor above the budget is cut

- **WHEN** a subnet declares 48 GB VRAM and the budget band is the 24 GB
  consumer band
- **THEN** it is cut at the hardware rung with a reason carrying 48 GB and
  the band's 24 GB

#### Scenario: A declared floor inside the budget is netted

- **WHEN** a subnet declares 16 GB VRAM and the budget band is the 24 GB
  consumer band
- **THEN** it survives, and its net figure is gross minus the consumer
  band's rent

#### Scenario: No GPU code is costed as CPU and marked assumed

- **WHEN** a subnet's verdict is `possible`
- **THEN** its required band is the CPU band with no rent, and the view
  marks the band as assumed

#### Scenario: Unknown hardware is assumed to fit and says so

- **WHEN** a subnet's verdict is unknown
- **THEN** it is costed at the budget band's rent and the view marks the
  band as assumed

#### Scenario: No band means no ranking

- **WHEN** no budget band is configured
- **THEN** every surviving subnet is stored as unrated `no-budget-band` and
  none is ranked on gross income

### Requirement: Price-based figures are at spot and carry a subnet-wide sale haircut

Every TAO figure derived from the alpha price SHALL be labelled as valued at
the spot price of the read block wherever it is shown. The exit haircut
SHALL be the slippage of selling the subnet's whole daily participant
emission, times a configured sale fraction, into the read block's pool, not
only the entrant's own sale. The view SHALL carry the pool depth in days of
emission.

#### Scenario: A thin pool is haircut for the whole subnet's sale

- **WHEN** a subnet distributes 7,200 alpha per day into a pool holding
  89,898 alpha, with a sale fraction of 1.0
- **THEN** the haircut is the slippage of selling 7,200 alpha into that
  pool, and the pool depth is reported as about 12.5 days

#### Scenario: The label travels with the figure

- **WHEN** the board or a tool presents a TAO per month figure
- **THEN** the same view states that it is valued at the read block's spot
  price

### Requirement: Payback on the registration burn is reported

The view SHALL report payback days: the registration burn in TAO divided by
the net income per day. Payback SHALL be absent when net income is unknown
or not positive, never zero or negative.

#### Scenario: Positive net income gives a payback

- **WHEN** the registration burn is 0.5 TAO and net income is 15 TAO per
  month
- **THEN** payback is 1.0 day

#### Scenario: No net income gives no payback

- **WHEN** net income is unknown or at or below zero
- **THEN** payback is absent

### Requirement: The board query returns a compact row

The board tool SHALL return each ranked subnet as a fixed compact row: rank,
netuid, name, ranked mechanism, entrant figure in alpha per day and TAO per
month at spot, parity share, 25th-percentile and median earner, earning and
registered UIDs, the miner-activity facts, consensus mode, top-1 share,
price, haircut, pool depth, payback, required band, entry context,
feasibility verdict with its evidence path, and confidence. Cut and
unrated subnets SHALL carry netuid, name and reason. Full detail SHALL stay
on the single-subnet tool.

#### Scenario: Board rows are bounded

- **WHEN** the board tool returns ten ranked subnets
- **THEN** each row carries only the compact fields, and no raw pool
  reserve, issuance, or per-mechanism dump

#### Scenario: Detail is still reachable

- **WHEN** a reader asks the single-subnet tool for a ranked subnet
- **THEN** every stored economics field and mechanism row is returned

### Requirement: Miner-activity facts are stated as observations

For each subnet the screen SHALL report, as context and not as a ranking
input, these counts read at the snapshot block:
- UIDs with nonzero incentive
- UIDs registered in the last 7 days
- UIDs given nonzero weight by at least one permit-holding validator whose
  last update is within the subnet's activity cutoff
- the most UIDs any one such validator weights
- hotkeys that served an axon in the last 7 days

Each count SHALL carry its exact definition. No count SHALL be labelled as
active or idle miners. An unread input SHALL make its count unknown, never
zero.

#### Scenario: A top-k weighting pattern is shown as a fact

- **WHEN** every fresh validator row on a subnet weights at most 5 UIDs
- **THEN** the view reports the widest row as 5 and makes no claim about the
  subnet's payout design or how many miners are trying

#### Scenario: A stale validator row is not counted

- **WHEN** a permit-holding validator last updated outside the activity
  cutoff
- **THEN** the UIDs only it weights are not in the weighted count

#### Scenario: Weights label carries the reveal lag

- **WHEN** a subnet runs commit-reveal weights
- **THEN** the weighted count is labelled as reflecting the last revealed
  weights

#### Scenario: Rounding is disclosed

- **WHEN** the earning count is shown
- **THEN** the view states that a share below 1/65535 of a mechanism's pool
  reads as zero

#### Scenario: Axon count stores no address

- **WHEN** axon entries are read for a subnet
- **THEN** only the count of entries served in the last 7 days is stored,
  the label says validators are included and that many subnets do not use
  axons, and no address or port is stored or returned

#### Scenario: Unread input is unknown, not zero

- **WHEN** the registration blocks of a subnet were not read
- **THEN** its 7-day registration count is unknown

### Requirement: Consensus mode is tracked per subnet

Each pass SHALL record every subnet's epoch consensus mode, Yuma or Null,
read from chain with the runtime default (Yuma) applied only to a readable
unset entry. A change from the previous recorded mode SHALL be stored with
its block. A first observation SHALL be stored without a change. Mode
changes SHALL NOT send alerts. The board and the query surface SHALL show
the count per mode, the Null subnets, and for each the block of the
recorded switch or "first seen by Atlas" with its date.

#### Scenario: First pass seeds without switches

- **WHEN** the tracker runs for the first time over 128 subnets
- **THEN** 128 observations are stored and no switch is recorded

#### Scenario: A switch is recorded, not paged

- **WHEN** a subnet recorded as Yuma is read as Null
- **THEN** one switch is stored with both modes and the block, and no
  Telegram alert is sent

#### Scenario: A Null subnet is flagged

- **WHEN** a ranked subnet runs Null
- **THEN** its view says one validator's weights set all miner pay on that
  subnet

#### Scenario: Pending owner pruning is flagged

- **WHEN** a Null subnet has a pending pruning target below its registered
  count
- **THEN** the view shows the target and the registered count and says that
  pruning removes the lowest-emission UIDs that are not immune

#### Scenario: Unread mode is unknown

- **WHEN** a subnet's consensus entry fails to decode or holds an unknown
  value
- **THEN** its mode is recorded as unknown, never as Yuma, and no switch is
  recorded from it

### Requirement: History marks a change of economics model

Every economics row SHALL record the model version it was classified
under. The history tool SHALL mark each observation stored under a model
other than the newest observation's, and SHALL say that figures across
that boundary are not a change in the subnet. Rows stored before versions
were recorded SHALL count as an earlier model.

#### Scenario: A model change is not read as a collapse

- **WHEN** a subnet's history holds a row from before this change and one
  from after it
- **THEN** the older row is marked as from an earlier model and the
  response carries a note not to compare their figures as a change
