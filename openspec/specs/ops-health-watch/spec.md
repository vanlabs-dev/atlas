# ops-health-watch Specification

## Purpose
An out-of-band health watch that runs outside Hermes and the alert scan.
It pages when the Hermes gateway, the alert scan, the LLM, or any Atlas
systemd unit stops working, and pages once more when it recovers.

## Requirements

### Requirement: Health watch runs outside Hermes on its own timer

The health watch SHALL run as its own user timer at least every 5
minutes. It SHALL NOT depend on the Hermes gateway, the alert scan, or any
LLM call to detect a fault or to send a page. Every page it sends SHALL be
rendered from a fixed template.

#### Scenario: Gateway down and LLM unavailable
- **WHEN** the Hermes gateway is stopped and the LLM is unreachable
- **THEN** the health watch still runs on schedule and sends its page
  without calling the LLM

### Requirement: Gateway outage pages once after two failed checks

The health watch SHALL treat the gateway as down when any of these holds:
- the unit is not active;
- the restart count rose since the last check;
- the gateway state file is missing, unreadable, not `running`, or older
  than 10 minutes;
- the state file's pid differs from the unit's main pid;
- Telegram is not `connected` or needs attention.

A page SHALL be sent only after two consecutive failed checks. Exactly one
page SHALL be sent per outage, and one recovery note when a check passes
again.

#### Scenario: Operator restart does not page
- **WHEN** the gateway restarts and the next check finds it healthy
- **THEN** no page is sent

#### Scenario: Gateway stays down
- **WHEN** two consecutive checks find the gateway inactive, and later
  checks still do
- **THEN** exactly one outage page is sent, naming the failed check

#### Scenario: Recovery
- **WHEN** a check passes after an outage was paged
- **THEN** one recovery note is sent, and a later outage pages again

#### Scenario: Unknown state file shape
- **WHEN** the state file cannot be parsed or lacks the expected fields
- **THEN** the check fails as "cannot read gateway state", and the watch
  does not crash

### Requirement: Stale alert scan pages once

The alert scan SHALL record the time of each completed run. When the last
completed scan is older than a configured number of hours (default 3),
the health watch SHALL page once for that outage and send one recovery
note when a scan completes again.

#### Scenario: Scan stops running
- **WHEN** no scan has completed for more than 3 hours
- **THEN** one page says alerts are not being checked and gives an
  inspect command

### Requirement: LLM outage pages once

The health watch SHALL treat the LLM as unavailable when either of these
holds over the last configured window (default 2 hours):
- the plain-English rewrite fell back for a model or auth reason on every
  attempt, with at least 2 attempts;
- the Hermes logs record an authentication failure newer than the last
  successful model reply.

It SHALL page once per outage and send one recovery note. It SHALL NOT
treat a CLI login flag as proof of a working login.

#### Scenario: Login expired
- **WHEN** the Hermes log records "Failed to authenticate" and no model
  reply has succeeded since
- **THEN** one page says the Claude login needs renewing

#### Scenario: Single fallback
- **WHEN** one rewrite falls back on a timeout and the next succeeds
- **THEN** nothing is paged

### Requirement: Atlas unit failures page once per streak

Every Atlas systemd unit SHALL trigger a failure notifier when it fails.
The notifier SHALL send one fixed-text page per unit per failure streak.
The page SHALL name the unit and give a journal command to inspect it. It
SHALL NOT include raw log lines. When the unit later succeeds, the streak
SHALL end and the next failure SHALL page again. The notifier SHALL NOT
cover itself or the Hermes gateway.

#### Scenario: Repeated failure
- **WHEN** `atlas-fleet.service` fails on three consecutive runs
- **THEN** exactly one page names `atlas-fleet.service`

#### Scenario: Failure after recovery
- **WHEN** a unit fails, then succeeds, then fails again
- **THEN** two pages are sent in total
