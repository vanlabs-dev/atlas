# Spec Delta

## MODIFIED Requirements

### Requirement: Data pages
The site SHALL serve pages for mining triage, fleet attention with rotation signals, network pulse, and the runtime-upgrade timeline.

#### Scenario: Each page renders
- **WHEN** a visitor opens any of the four data pages
- **THEN** the page renders its data and shows when that data was produced

#### Scenario: Stale data
- **WHEN** the data is older than 48 hours
- **THEN** the page shows a visible stale label next to the data age

#### Scenario: Stale at build time
- **WHEN** the data is already older than 48 hours when the page is built
- **THEN** the server-rendered HTML carries the stale label, before any script runs

#### Scenario: Stale at render time
- **WHEN** the data is already older than 48 hours when the server renders the page
- **THEN** the server-rendered HTML carries the stale label, before any script runs

#### Scenario: Home page data age
- **WHEN** a visitor opens the home page
- **THEN** it shows when its data was produced, with the same stale rule as the data pages

### Requirement: Single typed data layer
Every page SHALL read data only through one typed data layer, so that replacing fixtures with live data changes that layer alone.

#### Scenario: Swap source
- **WHEN** the fixture source is replaced by another source with the same types
- **THEN** no page component changes

### Requirement: Operator-free data
Site data SHALL be subnet-level facts only. It SHALL NOT include the owner's holdings, positions, hotkeys, wallets, or rotation decisions. A private-party address is any address not on the public-identifier allowlist; the owner's own addresses are private.

#### Scenario: Allowlisted export
- **WHEN** the export script reads the live stores
- **THEN** each record contains only fields on a named allowlist, and an unlisted field in the source is dropped

#### Scenario: Allowlisted publish
- **WHEN** the Pi publisher composes a board for the hosted store
- **THEN** each record contains only fields on the same named allowlist, and an unlisted field in the source is dropped

## ADDED Requirements

### Requirement: Pages read published data at request time
The data layer SHALL read each board from the hosted store when a page is rendered, and SHALL refresh its cached copy at least every 15 minutes. A data change in the hosted store SHALL reach the pages without a commit, a push or a deploy.

#### Scenario: New board published
- **WHEN** the publisher uploads a newer board
- **THEN** the page that shows it renders the newer data within 15 minutes, with no new deploy

#### Scenario: Records are still projected
- **WHEN** a board read from the hosted store carries a field the type does not declare
- **THEN** the built pages and their client payloads do not contain that field name or its values

### Requirement: Pages fall back to the last good data
When the hosted store cannot be read, a page SHALL serve the last copy it read successfully. With no such copy, it SHALL serve the committed fixture. Either way, the page SHALL show the age of the data it serves and apply the stale rule to it.

#### Scenario: Store down with a cached copy
- **WHEN** a refresh from the hosted store fails and an earlier read succeeded
- **THEN** the page keeps serving the earlier data with its own produced time

#### Scenario: Store down with no cached copy
- **WHEN** the hosted store cannot be read and no earlier read succeeded
- **THEN** the page serves the committed fixture and shows its age, with the stale label when it is older than 48 hours

#### Scenario: Store not configured
- **WHEN** the site is built or served without the hosted-store settings
- **THEN** every page renders from the committed fixtures and the build does not fail
