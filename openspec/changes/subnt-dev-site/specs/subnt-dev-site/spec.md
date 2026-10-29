# Spec Delta

## Purpose

Defines the subnt.dev site: a public page set that explains Atlas and lets
the owner glance at Atlas data, built on a typed data layer with fixtures.

## ADDED Requirements

### Requirement: Home page explains Atlas
The site SHALL serve a home page that states what Atlas is without prior context.

#### Scenario: First visit
- **WHEN** a visitor opens the home page
- **THEN** the first screen states what Atlas is and links to the four data pages

### Requirement: Data pages
The site SHALL serve pages for mining triage, fleet attention with rotation signals, network pulse, and the runtime-upgrade timeline.

#### Scenario: Each page renders
- **WHEN** a visitor opens any of the four data pages
- **THEN** the page renders its data and shows when that data was produced

### Requirement: Single typed data layer
Every page SHALL read data only through one typed data layer, so that replacing fixtures with live data changes that layer alone.

#### Scenario: Swap source
- **WHEN** the fixture source is replaced by another source with the same types
- **THEN** no page component changes

### Requirement: Fixture hygiene
Committed fixtures SHALL contain no secrets, wallet addresses of private parties, tokens, or internal host details.

#### Scenario: Scrubbed export
- **WHEN** fixtures are generated from the live Atlas stores
- **THEN** a scrub check passes before the fixtures are committed

### Requirement: Dark mode
The site SHALL ship a dark theme as the default design target and honour the system colour scheme.

#### Scenario: System dark
- **WHEN** the system prefers a dark scheme
- **THEN** the site renders the dark theme with readable contrast

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
