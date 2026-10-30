# subnt-dev-site Specification

## Purpose
Defines the subnt.dev site: a public page set that explains Atlas and lets
the owner glance at Atlas data, built on a typed data layer with fixtures.

## Requirements

### Requirement: Home page explains Atlas
The site SHALL serve a home page that states what Atlas is without prior context.

#### Scenario: First visit
- **WHEN** a visitor opens the home page at 1280x720 or 390x844
- **THEN** the first screen shows one sentence stating what Atlas is and links to the four data pages, with no scrolling

### Requirement: Data pages
The site SHALL serve pages for mining triage, fleet attention with rotation signals, network pulse, and the runtime-upgrade timeline.

#### Scenario: Each page renders
- **WHEN** a visitor opens any of the four data pages
- **THEN** the page renders its data and shows when that data was produced

#### Scenario: Stale data
- **WHEN** the data is older than 48 hours
- **THEN** the page shows a visible stale label next to the data age

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

### Requirement: Fixture hygiene
Committed fixtures SHALL contain no secrets, private-party addresses, tokens, or internal host details, and SHALL use aged or rounded values, not live state.

#### Scenario: Scrubbed export
- **WHEN** fixtures are generated from the live Atlas stores
- **THEN** the scrub test passes before the fixtures are committed

#### Scenario: Planted leak
- **WHEN** a token, IP, hostname, or private address is planted in a fixture
- **THEN** the scrub test fails

### Requirement: Dark mode
The site SHALL ship a dark theme as the default design target and honour the system colour scheme.

#### Scenario: System dark
- **WHEN** the system prefers a dark scheme
- **THEN** the site renders the dark theme with readable contrast

### Requirement: Accessibility
Every page SHALL score at least 95 in Lighthouse accessibility and meet WCAG AA text contrast in the dark theme.

#### Scenario: Audit
- **WHEN** Lighthouse and a contrast check run on each page
- **THEN** each page scores 95 or higher and no text fails AA

### Requirement: Reduced motion
The site SHALL disable non-essential animation when the visitor prefers reduced motion.

#### Scenario: Reduced motion set
- **WHEN** `prefers-reduced-motion: reduce` is set
- **THEN** no page animates position, scale, or opacity beyond instant state changes

### Requirement: Out-of-scope features absent
The site SHALL NOT include logins, wallet tracking, trading advice, or public chat.

#### Scenario: Surface check
- **WHEN** the built site is reviewed
- **THEN** it exposes none of those features

### Requirement: Upgrade job isolation
The runtime upgrade scope gate SHALL reject any change to a path under `web/`, and pushes that touch only non-site paths SHALL NOT trigger a site deploy.

#### Scenario: Scope gate
- **WHEN** a diff contains a path under `web/`
- **THEN** the scope check fails

#### Scenario: Upgrade push
- **WHEN** a commit changes only corpus or chain-reader paths
- **THEN** the Vercel ignored-build step skips the build

#### Scenario: Unknown previous commit
- **WHEN** the previous deployed SHA is unavailable
- **THEN** the ignored-build step builds
