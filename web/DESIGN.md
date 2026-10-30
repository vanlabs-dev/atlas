# subnt.dev design

Approved: 2026-10-30 (owner, comp E "Strata").

Reference comp: `docs/greenfield/subnt-dev-site/comps/e-strata.html`
(screenshots beside it). The comp reads a `DATA_PLACEHOLDER` built from
the fixtures. It is a picture of the system, not code to copy.

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

## Rules relaxed from design-taste-frontend

The owner relaxed the house rules for this site. They are allowed:

- tabular figures with a slightly technical feel, and a monospace face
  inside real data tables;
- one scrim gradient behind the hero copy, for legibility over the
  strata;
- a living background (the strata), which the inspector may read as
  motion or decoration.

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
  only. h1 clamp(48px, 6.6vw, 104px), leading 0.96, tracking -0.025em.
  Section heads clamp(40px, 4.4vw, 64px). Large figures (KPIs) at 64px.
- Text and UI: Schibsted Grotesk 400, 500, 600. Body 16px, lead 20px,
  small 13px.
- Tabular figures on numbers only (`dd`, numeric `td`, block readout).
  Not on body text: Schibsted's tabular punctuation spaces commas apart.
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

## Shape

- Primary button: solid ink, radius 4px, 46px tall. Secondary action:
  a text link with an underline. Panels: radius 10px, no border, no
  shadow. Different radii per element type on purpose.

## The strata (signature element and live control)

- A full-bleed `<canvas>` behind the hero. 128 rows, one per subnet
  (netuid 1 to 128). 90 columns, one per day, newest on the right.
- Each cell's mark height and alpha scale with `log1p(commits that day)`.
  Head-tier rows are drawn in accent, the rest in ink at low alpha. The
  selected or hovered row draws in accent 2 with a lit baseline.
- Block clock: Bittensor seals a block every 12 s. On each block the
  newest column lights a seal line (see "Block tick" below). The header shows "est. block N" and a 12 s progress line.
  "est." stays until a live block source exists.
- Interaction: pointing at a row opens that subnet in the panel. Click
  selects it. Keyboard: the panel holds a subnet picker (arrow keys or
  a number field) that drives the same selection. The canvas has an
  `aria-label`, and the panel is `aria-live="polite"`.
- Reduced motion: no seal line flash and no progress line. The block
  number still updates as text.
- Data: real daily commit counts per subnet for 90 days (allowlisted
  field `daily` in `fleet.activity`, 90 integers, oldest first). The
  export runs the activity metric's own `git log --no-merges` in each
  clone and bins back from that subnet's latest activity pass, the same
  instant the fleet board reads. So the last 7 and 30 bins match the
  board's counts (a test checks this). A subnet with no readable clone
  gets `null`, never zeros. The comp derived days from the 7- and
  30-day counts. The build does not.
- Block tick (owner, 2026-10-30): the field stays still. Each block
  advances the counter and the progress line and lights a seal line on
  the newest column. It never adds or removes activity.

## Boards (mining, fleet, network, upgrades)

- Same tokens and type. Shell: a slim top bar (wordmark, four links,
  block readout). No icon rail.
- Each board: a Newsreader title, one finding sentence, the data age
  and stale label, then the content.
- Layout: asymmetric, with a 4/8 split where a board has a figure
  column. Large Newsreader figures for the counts. Tables with rules,
  right-aligned tabular numbers, and a 30-day activity lane (a tiny
  strata strip) per subnet where daily data exists.
- Filters: text tabs, with the selected one marked by a 1px accent
  underline as wide as its label.
- Charts: flat accent bars or lines, a faint 3-line scale, dates on the
  ends, no legend for a single series.

## Motion list

1. The strata block tick (signature): counter, progress line, seal line.
2. Hover and press feedback on rows, links and buttons (opacity or
   colour only, under 200 ms).
3. Panel content swap on selection (150 ms crossfade).

That is all. No entrance animations on sections.

## Checks to keep

Lighthouse a11y of 95 or more in both schemes, AA contrast, the reduced
motion check, the first-screen check at 1280x720 and 390x844, the
fixture scrub and allowlist tests, and operator-free data.
