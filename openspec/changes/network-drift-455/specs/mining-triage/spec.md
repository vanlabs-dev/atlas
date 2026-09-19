## MODIFIED Requirements

### Requirement: The cut ladder is ordered and every exclusion records its reason

The screen SHALL apply exclusions as an ordered ladder and SHALL record, for
every excluded subnet, the gate at which it left and the value that
triggered it. An excluded subnet SHALL remain retrievable with its reason;
exclusion SHALL NOT be implemented as omission.

The ladder SHALL begin with the **pool-side emission switch**, and SHALL name
it as a switch rather than as the emission gate. The two are different
mechanisms and conflating them misreads the board: the emission-gate bar is a
continuous function of a subnet's demand share, while this switch is a binary
root-settable state that can be flipped for many subnets at once without any
demand moving. A subnet with the switch off still distributes alpha to its
miners, because the participant distribution runs regardless; what it loses is
the TAO inflow backing that alpha, so the alpha's price decays and
TAO-denominated income tends to zero. The recorded reason SHALL say that,
SHALL NOT claim the subnet pays nothing, and SHALL NOT attribute the
exclusion to the subnet's demand or to the bar.

Because this rung is driven by an external switch rather than by the subnet's
own economics, a change in the board's ranked count that follows a switch
transition SHALL be attributable to it: the board SHALL carry the reference
block of the switch state it was built from, so a jump in the ranked count can
be read against the transition record rather than mistaken for a change in
what subnets are worth entering.

The switch rung is followed by an on-chain identity rung. A subnet whose
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

- **WHEN** a subnet reports its pool-side emission switch off
- **THEN** it is excluded at the switch rung with a reason naming the switch,
  unbacked alpha and a decaying price, not absent payment and not the
  emission-gate bar, and it remains retrievable from the store and the query
  surface as an excluded subnet

#### Scenario: A switch flip is attributable on the board

- **WHEN** the ranked count changes between passes because the pool-side
  emission switch changed for one or more subnets
- **THEN** the board carries the reference block of the switch state it was
  built from, so the change can be read against the recorded transition

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
