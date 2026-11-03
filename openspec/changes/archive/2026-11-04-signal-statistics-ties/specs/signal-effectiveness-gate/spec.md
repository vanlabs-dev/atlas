## MODIFIED Requirements

### Requirement: Promotion to instant requires a filled ledger read that beats the baseline

A class SHALL be promoted from `shadow` or `briefing` to `instant` only by an
explicit operator decision recorded in the project decision log, taken against
an effectiveness read in which that class has, at the 7-day horizon, at least
a configured minimum number of distinct event moments with filled outcomes,
and a 95% interval for the median paired excess return over the fleet
baseline whose lower bound is above zero. An event moment is one entry price
vector: every outcome entered against the same vector shares one moment,
whatever the number of netuids or events behind it.

The recorded decision SHALL state the class, the horizon, the filled count,
the distinct event count, the median excess return and its interval, the
class median, and the baseline median as read at the time of the decision.
A promotion SHALL NOT be justified by a horizon whose outcomes are majority
pending.

#### Scenario: Insufficient sample blocks promotion

- **WHEN** a class's 7-day horizon has fewer distinct event moments with
  filled outcomes than the configured minimum
- **THEN** the class is not eligible for promotion and the effectiveness
  report states that its sample is insufficient

#### Scenario: Many rows from few moments do not meet the floor

- **WHEN** a class has 87 filled 7-day outcomes entered against 8 price
  vectors and the minimum is 30
- **THEN** the report counts 8 event moments and states that the sample is
  insufficient

#### Scenario: Interval touching zero does not beat the baseline

- **WHEN** a class meets the floor and its median excess return is positive
  but the interval's lower bound is at or below zero
- **THEN** the report states that the class does not beat the baseline

#### Scenario: Majority-pending horizon cannot justify promotion

- **WHEN** a class's horizon has more pending outcomes than filled outcomes
- **THEN** that horizon is not eligible to justify a promotion, whatever its
  median shows

#### Scenario: Promotion is recorded with its evidence

- **WHEN** a class is promoted to the instant tier
- **THEN** the decision log carries the class, horizon, filled count,
  distinct event count, median excess return and interval, class median, and
  baseline median that justified it
