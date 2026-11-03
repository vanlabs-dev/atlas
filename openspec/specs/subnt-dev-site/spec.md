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

#### Scenario: Stale at build time
- **WHEN** the data is already older than 48 hours when the page is built
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

### Requirement: Fixture hygiene
Committed fixtures SHALL contain no secrets, private-party addresses, tokens, or internal host details, and SHALL use rounded values, not exact live state. The export SHALL read the latest stored pass of each input; it SHALL NOT pair an economics pass with a feasibility scan by an age cutoff.

#### Scenario: Scrubbed export
- **WHEN** fixtures are generated from the live Atlas stores
- **THEN** the scrub test passes before the fixtures are committed

#### Scenario: Planted leak
- **WHEN** a token, IP, hostname, or private address is planted in a fixture
- **THEN** the scrub test fails

#### Scenario: Newer scan is not erased
- **WHEN** a subnet's feasibility scan is newer than the latest mining pass
- **THEN** the exported mining row carries that scan's verdict, not a blank

#### Scenario: Rehearsal cannot overwrite committed fixtures
- **WHEN** the export runs with an output directory
- **THEN** it writes there only, and it refuses the committed fixture directory unless no output directory is given

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

### Requirement: Served data is limited to typed fields
The data layer SHALL pass each page only the fields its type declares. A field present in a fixture but absent from the type SHALL NOT reach the HTML or the client payload.

#### Scenario: Legacy fixture field
- **WHEN** a committed fixture still carries a field the type no longer declares
- **THEN** the built pages and their client payloads do not contain that field name or its values

### Requirement: Rent and hardware rung stay off the site
Site data SHALL NOT include rent, any income or price figure for a mining slot, payback, the required hardware band, whether that band was assumed, or cut detail text. Atlas ranks by net income, so an income figure beside the rank bounds the rent. A hardware cut SHALL render as a fixed public reason.

#### Scenario: Banned field in the allowlist
- **WHEN** the export allowlist maps any of those source fields
- **THEN** the allowlist test fails

#### Scenario: Income figure beside the rank
- **WHEN** the export allowlist maps a gross income, entrant figure or alpha price field
- **THEN** the allowlist test fails, and the built site carries no such field

#### Scenario: Hardware cut
- **WHEN** a subnet is cut because its declared GPU need exceeds the budget band
- **THEN** its row reads "Needs a larger GPU" and states no band name or rent

### Requirement: Mining view follows the stored ranking
The mining page SHALL order ranked subnets by the stored Atlas rank, then cut subnets with their public reason, then subnets with neither. No cut subnet SHALL be named as the head. An unmapped cut or unrated code SHALL render as a named gap, never as a raw token.

#### Scenario: Cut subnet has the largest raw figure
- **WHEN** the largest raw income figure belongs to a cut subnet
- **THEN** it is listed after every ranked subnet and the headline names the rank-1 subnet

#### Scenario: Unknown cut code
- **WHEN** a row carries a cut reason the site has no wording for
- **THEN** the row reads as an unnamed cut reason, not the code

### Requirement: Mining figures are labelled as a model
The Atlas rank SHALL be described as the order of a model estimate after hardware cost, valued at the spot price of the stated read block, and the site SHALL say it publishes the order, not the figures. A `possible` scan verdict SHALL render as "No GPU code found", with the count of files that mention a GPU where any do, and never as running on a CPU or with a VRAM figure. The top-earner share SHALL state that it excludes the owner.

#### Scenario: No GPU code
- **WHEN** a row's verdict is `possible` and 3 files mention a GPU
- **THEN** it reads "No GPU code found; GPU mentioned in 3 files" and shows no VRAM figure

#### Scenario: Rank label
- **WHEN** the mining page shows the Atlas rank
- **THEN** the same view names it the order of a model estimate at spot, states the read block, and shows no income figure

### Requirement: No direction cue
The site SHALL NOT state which way a price should move or which of code and price leads, in words, glyphs or a signed gap. The code-against-price gap SHALL render as an unsigned distance in places.

#### Scenario: Negative gap
- **WHEN** a subnet's code rank is 47 places behind its price rank
- **THEN** the site shows "47 places apart" and no "ahead", "behind", sign or arrow for that gap

#### Scenario: Payload has no cue
- **WHEN** the built site is searched for the cue field name
- **THEN** it is absent

### Requirement: Labels match their definitions
A label SHALL hold for every row it is on. "Code and price apart" SHALL appear only at a gap of 40 places or more. A cold subnet SHALL be described as having no commits for 30 days or more in the tracked repository. A list cut to N items SHALL say it shows the N newest, not N of a total. No page SHALL call a data day "today" unless it is the visitor's current UTC day.

#### Scenario: Small gap
- **WHEN** a row's dominant reason is divergence with a gap of 12
- **THEN** it does not read "Code and price apart"

#### Scenario: Capped list
- **WHEN** 30 rotation events were exported and 10 are shown
- **THEN** the page says it shows the 10 newest and states no total

#### Scenario: Old data day
- **WHEN** the newest data day is 29 Oct and the page is viewed on 4 Nov
- **THEN** no element calls 29 Oct "today"

### Requirement: Exported activity matches the board
Daily commit bins SHALL count the same commits the activity metric counts: bot and CI authors excluded by the same patterns, and the same window edges, so the last 7 and 30 bins sum to the board's 7- and 30-day counts for that pass.

#### Scenario: Bot commit and window edge
- **WHEN** a clone holds one human commit exactly 7.0 days before the pass and one bot commit yesterday
- **THEN** the last seven bins sum to the stored 7-day count, which counts the human commit and not the bot commit

### Requirement: Signals export only named public classes
The signals export SHALL include only signal classes the site names and only non-shadow tiers. Any other class SHALL be dropped at export.

#### Scenario: Unnamed class
- **WHEN** the store holds a `watchlist` or shadow-tier signal
- **THEN** no exported record carries it

### Requirement: Empty and missing values render safely
Every page SHALL render with an empty list or a null figure: a missing percentage reads as a dash without a unit, an average over no values reads as a dash, and an empty board renders its gap instead of failing the build.

#### Scenario: Empty fleet board
- **WHEN** the fleet fixture has no rows
- **THEN** the fleet and home pages build and state that no subnet is on the board
