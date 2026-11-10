# site-data-publish Specification

## Purpose
Composes the public subnt.dev boards from the Atlas stores on the Pi and
publishes them to the hosted store the site reads, so that the site shows
current Atlas data without a commit or a deploy.

## Requirements

### Requirement: Boards are composed read-only from the Atlas stores
The publisher SHALL build the mining, fleet, network and upgrades boards from the latest stored passes. It SHALL open every Atlas store read-only and SHALL make no chain, provider or model call.

#### Scenario: No store is written
- **WHEN** a publish run completes
- **THEN** no row in any Atlas store has been inserted, updated or deleted

#### Scenario: Each board carries its source time
- **WHEN** a board is composed
- **THEN** its generated time is the time of the stored pass it was built from, not the time of the publish run

### Requirement: Only allowlisted, rounded fields are published
Each published record SHALL contain only the fields named for its kind in the shared field allowlist, with numeric values rounded to four significant digits. A field the stores add later SHALL NOT be published until the allowlist names it.

#### Scenario: Unlisted source field
- **WHEN** a store row carries a field the allowlist does not name
- **THEN** the published board does not contain that field

#### Scenario: Same output as the fixture export
- **WHEN** the publisher and the fixture export build a board from the same source records
- **THEN** the two boards are identical

### Requirement: A board that fails the scrub is not published
Before upload, the publisher SHALL run the same scrub the committed fixtures pass. A board that fails SHALL NOT be uploaded, and the board already in the hosted store SHALL stay as it was.

#### Scenario: Planted leak
- **WHEN** a composed board contains a token, IP address, hostname, private-party address or banned field
- **THEN** that board is not uploaded and the run reports a scrub failure

#### Scenario: Other boards still publish
- **WHEN** one board fails the scrub
- **THEN** the boards that pass are still uploaded

### Requirement: Publishing follows the Atlas passes
The publisher SHALL run at least hourly, after the hourly Atlas passes. It SHALL upload a board only when that board's generated time or content differs from the copy in the hosted store.

#### Scenario: New network pass
- **WHEN** the hourly probe has recorded a new pass
- **THEN** the network board in the hosted store reflects that pass within one hour

#### Scenario: Nothing new
- **WHEN** no board has changed since the last upload
- **THEN** the run uploads nothing and exits successfully

### Requirement: Publish failures are reported and fail closed
A failed upload, an unreachable hosted store or a missing credential SHALL fail the run with a non-zero exit, so the Atlas job-failure alert fires. A failure SHALL NOT delete or blank a board in the hosted store.

#### Scenario: Hosted store unreachable
- **WHEN** the hosted store cannot be reached
- **THEN** the run exits non-zero and the boards in the hosted store are unchanged

#### Scenario: Missing secret key
- **WHEN** the publisher's secret key is not set
- **THEN** the run exits non-zero before composing any board

### Requirement: Only the publisher can write the hosted store
The hosted store SHALL allow public reads of published boards and SHALL reject writes made with the public key. The write credential SHALL live only on the Pi, outside the repository, and SHALL never be printed or logged.

#### Scenario: Write with the public key
- **WHEN** a client tries to insert, update or delete a board using the public key
- **THEN** the hosted store rejects the request

#### Scenario: Credential stays out of output
- **WHEN** a publish run fails
- **THEN** its log and its error text do not contain the secret key
