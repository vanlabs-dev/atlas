# subnt.dev design

Approved: 2026-10-30 (owner, comp E "Strata"). Revised the same day:
comp F, "Strata as an instrument", approved by the owner (dashes
variant, with wayfinding and the idle tour).

Reference comp: `docs/greenfield/subnt-dev-site/comps/f-instrument.html`
(real fixture data inlined; screenshots beside it). It is a picture of
the system, not code to copy. Comp E stays beside it for history.

## History

- First build: `design-taste-frontend` direction "One motif", bottle
  green and gold, General Sans. Rejected by the owner as flat and
  boring, with a two-colour system that did not work.
- Comps A (Instrument), B (Telemetry), C (Aurora) and D (C's layout in
  A's colours) were rendered on real data. B was rejected. D was
  rejected for AI tells: the "X, watched" headline formula, the italic
  serif keyword, and a generic aurora background.
- E replaced those with the choices below, after research into 2026
  AI-default patterns (Paralect's 21 patterns, the Sailop 2026 report).
- E, once built, read as distinctive but not excellent: the field was
  even static with no shape or scale, the hero was the stock "headline
  left, stat card right" layout, the block tick was invisible, and the
  figures had spacing defects. F keeps E's identity and fixes those.

## Rules relaxed from design-taste-frontend

The owner relaxed the house rules for this site. They are allowed:

- tabular figures with a slightly technical feel, and a monospace face
  inside real data tables;
- one scrim gradient behind the hero copy, for legibility over the
  strata;
- a living background (the strata), which the inspector may read as
  motion or decoration.

Relaxed by the owner on 2026-10-30, after the first Strata verify run,
because comp E breaks them by design:

- `headline-lines`: the approved h1 sets in three lines below desktop;
- `few-pictures`: the strata canvas is the picture, with no photographs;
- `still-page`: motion is the items in the motion list, with no
  entrance animations on sections.

Pass `inspect.mjs --allow <rule>` only for those rules, and use a
same-line `taste-skill-ignore` in lint. Every other house rule still
holds.

## Never use (AI tells)

- Headline formulas ("X, watched", "Transform your X", "The future of X").
- An italic or coloured keyword in a headline. Gradient text.
- Aurora or blurred colour blobs, glow, neon, background grids.
- Frosted glass on static cards.
- Geist, Inter, Instrument Serif, Space Grotesk.
- Pill badges, eyebrow labels, pulsing "live" dots, scroll-reveal on
  every block, icon-topped feature cards.
- Teal or green as a brand colour: it reads as taostats.

## Copy

- h1: "Atlas reads all 128 Bittensor subnets."
- Under it, one sentence with real figures from the data layer: "Code,
  chain and market, from one Raspberry Pi at home. In the last 30 days
  it read {commits30} commits across {repos} repositories."
- Plain, specific sentences. Digits, not words. No "we". No hype verbs.

## Type

- Display: Newsreader (Google, optical size axis), weight 500, upright
  only. h1 clamp(48px, 6.4vw, 112px), leading 0.95, tracking -0.028em.
  Section heads clamp(40px, 4.4vw, 64px). Large figures (KPIs) at 64px.
  Annotation name 40px.
- Text and UI: Schibsted Grotesk 400, 500, 600. The scale is five
  steps: 13 (labels, axis), 16 (body, tables), 20 (lead, findings),
  28 (sub-heads), 64 (section heads and figures), plus the h1. The hero
  sub-line is 22px.
- No tabular figures anywhere. Schibsted's tabular set gives the comma
  and the point a full figure width ("−27 .8%"). Numeric columns are
  right-aligned with proportional figures.
- Load both with `next/font/google` (self-hosted at build). Drop the
  Fontshare link.

## Colour (dark is the target; light follows the system)

| Role | Dark |
|---|---|
| ground | `#08090a` |
| surface 1 (panels) | `#0f1113` |
| surface 2 (row hover) | `#15181b` |
| rule | `#1d1f22` (8% white over ground, opaque) |
| ink | `#f2f3f5` |
| ink 2 (secondary) | `#a3a8b1` |
| ink 3 (labels) | `#7d838d` |
| accent (signal blue) | `#5d93ff` |
| accent 2 (active line) | `#a8c8ff` |
| down | `#f0646a` |

- No gradients except the hero scrim. Surfaces separate by tone, not
  border. Rules only in tables.
- Polarity colour only on "what moved" figures (price change). Positive
  uses accent 2, negative uses down. Everything else stays ink.
- Light scheme (derived 2026-10-30): ground `#f6f7f8`, surface 1
  `#eceef1`, surface 2 `#e2e5e9`, rule `#dcdfe3`, ink `#0c0e11`, ink 2
  `#464c56`, ink 3 `#5c626c`, accent `#2f6bf0`, accent 2 `#1d55c8`, down
  `#c2303a`. Accent is for lines and marks only; text that needs blue
  uses accent 2. Both schemes pass WCAG AA (Lighthouse `color-contrast`).
- Rules are opaque colours, not alpha: the inspector reads an alpha rule
  as solid black and flags it.

## Width

- Content runs to 1600px, centred, with a gutter of clamp(16px, 4vw,
  64px). The field runs edge to edge.

## Shape

- Primary button: solid ink, radius 4px, 46px tall. Secondary action:
  a text link with an underline. Panels: radius 10px, no border, no
  shadow. Different radii per element type on purpose.

## The strata (signature element and live control)

- A full-bleed `<canvas>` behind the hero. 128 rows, one per subnet,
  90 columns, one per day, newest on the right. Each mark's height and
  alpha follow `log1p(commits that day)`. Marks are separate dashes, one
  per day (the smoothed "bands" variant was rejected: it reads as speed
  lines).
- Rows are sorted like sediment: subnets with no readable code at the
  top (dotted baselines), then silent ones, then by 30-day commits,
  busiest at the bottom. The copy sits in the quiet top layers.
- It reads as a chart: a time axis under the field (dates and "90, 60,
  30 days ago"), a "today" edge on the right, and a right margin that
  names the quiet bands, the head of the fleet board and the five
  busiest, each with a connector to its row. Head-tier rows draw in
  accent, the rest in ink.
- The annotation replaces the card: subnet number, Newsreader name, one
  sentence, three figures, set in the quiet layers with an elbow line
  down to a dot on its row. The field is cleared behind it.
- Wayfinding: the row under the pointer lights as a band, a small tag at
  the pointer names it ("REAX 92, 106 commits in 30 days"), the
  annotation and the margin follow. Click pins a row. The field takes
  focus; the up and down arrows step one row. Idle, the annotation says
  how to explore.
- Idle tour (owner, 2026-10-30): after 5 s with no input, a ghost
  pointer glides slowly between random subnets with code (right half of
  the field), a new one every 6 to 9 s. The pointer tag and the
  annotation follow it row by row, as they follow the mouse (owner,
  2026-10-30). Any mouse move or key press
  hands control back. Off with reduced motion, on phones, and while the
  hero is out of view.
- Block clock: the "today" edge carries "est. block N" and a 12 s
  progress line, and flares on every block. The header carries the
  readout on the boards only. The field never adds or removes activity
  (owner, 2026-10-30). "est." stays until a live block source exists.
- Load: the 90 days replay left to right once, in 1.4 s, then settle.
- Phone: the copy first, the field below it as a 440px figure, the
  annotation under the field. No tour, no margin labels.
- Reduced motion: no replay, no tour, no flare, no progress line. The
  block number still updates as text.
- Data: real daily commit counts per subnet for 90 days (allowlisted
  field `daily` in `fleet.activity`, 90 integers, oldest first). The
  export runs the activity metric's own `git log --no-merges` in each
  clone and bins back from that subnet's latest activity pass, the same
  instant the fleet board reads. So the last 7 and 30 bins match the
  board's counts (a test checks this). A subnet with no readable clone
  gets `null`, never zeros.

## Boards (mining, fleet, network, upgrades)

- Same tokens and type. Shell: a slim top bar (wordmark, four links,
  block readout on the boards). No icon rail.
- Each board: a Newsreader title, one finding sentence, the data age
  and stale label, then the content.
- Layout: asymmetric, with a 4/8 split where a board has a figure
  column. Large Newsreader figures for the counts. Tables with rules,
  right-aligned numbers, no wrapping cells, and a 30-day activity lane (a tiny
  strata strip) per subnet where daily data exists.
- Filters: text tabs, with the selected one marked by a 1px accent
  underline as wide as its label.
- Charts: flat accent bars or lines, a faint 3-line scale, dates on the
  ends, no legend for a single series.

## Motion list

1. The strata block tick (signature): counter, progress line, today
   edge flare.
2. The strata load replay (1.4 s, once).
3. The idle tour and the pointer tag.
4. Hover and press feedback on rows, links and buttons (opacity or
   colour only, under 200 ms).

That is all. No entrance animations on sections.

## Checks to keep

Lighthouse a11y of 95 or more in both schemes, AA contrast, the reduced
motion check, the first-screen check at 1280x720 and 390x844, the
fixture scrub and allowlist tests, and operator-free data.
