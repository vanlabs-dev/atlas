# subnt.dev design

Approved: 2026-11-02 (owner, comp D "Flight and instrument"). It
replaces comp F, "Strata as an instrument" (2026-10-30), across the
whole site.

Reference comp: `docs/explore/home-motion/d-combined.html`, with the
picker `index.html` beside it (real
fixture data; screenshots beside it). It is a picture of the system,
not code to copy. Comps A to C and the comp F stills stay beside it for
history.

## History

- First build: `design-taste-frontend` direction "One motif", bottle
  green and gold, General Sans. Rejected by the owner as flat and
  boring, with a two-colour system that did not work.
- Comps A (Instrument), B (Telemetry), C (Aurora) and D (C's layout in
  A's colours) were rendered on real data. B was rejected. D was
  rejected for AI tells: the "X, watched" headline formula, the italic
  serif keyword, and a generic aurora background.
- E ("Strata") replaced those after research into 2026 AI-default
  patterns. Once built it read as distinctive but not excellent. F
  ("Strata as an instrument") kept E's identity and fixed those, and
  shipped on 2026-10-31.
- 2026-11-02: the owner found F not top of the line and asked for
  modern, motion-forward options. Research (Anthropic's Opus 5.5 guide:
  name the banned patterns; 2026 motion practice: one data object that
  moves for a reason) led to comps A "Re-sort", B "Fly-through" and C
  "Live instrument". The owner liked B's flight but found it flat once
  the motion ended, liked C's board hover, and asked to combine them
  with the look of the subnt trader design
  (`subnt-trader/web/design/home-options/b-lead-setup.html`). That is
  comp D. On review the owner found the red field overwhelming: red is
  now the accent only, and rises are green.

## Owner decisions, 2026-11-02

- Archivo replaces Newsreader and Schibsted Grotesk, site-wide.
- Red is the accent only: the main action, tab lines, head-tier marks,
  the band underline, falls. Never a whole field.
- Green is allowed for rises, and for nothing else. This overrides the
  green ban below for that one use.
- Dark is the target; a light scheme is derived and follows the system.
- The look applies to the whole site: header, footer and the four
  boards share the tokens.
- The brand is subnt.dev: the wordmark at the top left reads
  "subnt.dev" in Archivo display with a red dot, and page titles end in
  "| subnt.dev". Atlas is the system underneath that reads the data;
  copy names it as the reader, and the large "Atlas." closes every page
  in the footer.

## Rules relaxed from design-taste-frontend

The owner relaxed these house rules for this site:

- one scrim gradient behind the hero copy, for legibility over the
  field;
- a living background (the field), which the inspector may read as
  motion or decoration;
- `headline-lines`, `few-pictures`, `still-page`: pass
  `inspect.mjs --allow <rule>` for those rules only, and use a
  same-line `taste-skill-ignore` in lint;
- the inspector's `pinned-over-picture` warning: the flight's copy over
  the field is the concept;
- data panels on the home page (the lead panel, the band figures, the
  lists) carry `data-ui`: they are product fragments, and follow the
  app-screen rules inside. The boards are inspected with `--app`.

Added 2026-11-12 with the phone composition (the owner asked for a
phone-native site; these three follow from that and are open to a veto):

- `covered-text` at 390px only: the phone's bottom bar is fixed, so a
  heading passes under it while the page scrolls. The inspector exempts a
  top bar and not a bottom one. `npm run check:browser` proves the two
  bars are the only things that ever pass over large text, and that the
  last line of every page clears the bottom bar.
- the inspector's `side-scroll` warning on the home strip of statements:
  the strip is the phone's flight, one statement per view, with a pager
  that marks the position and steps it.
- the inspector's `numeric-align` warning on the boards at 390px: a table
  row is a list row there, and each figure sits under its own label.

Every other house rule still holds.

## Never use (AI tells)

- Headline formulas ("X, watched", "Transform your X", "The future of X").
- An italic or coloured keyword in a headline. Gradient text.
- Aurora or blurred colour blobs, glow, bloom, neon, background grids.
- Frosted glass on static cards.
- Geist, Inter, Instrument Serif, Space Grotesk.
- Pill badges and pill buttons, eyebrow labels above headings, pulsing
  "live" dots, scroll-reveal on every block, icon-topped feature cards,
  coloured borders on card tops or edges.
- The five Opus 5.5 defaults: a cream or off-white yellow ground, italic
  accent words, "01/02/03" labels, monospace labels, pill buttons.
- Teal, and green as a brand colour: it reads as taostats. Violet.

## Copy

- h1: "Atlas reads all 128 Bittensor subnets."
- Under it, one sentence with real figures from the data layer: "Code,
  chain and market, all from one Raspberry Pi. In the last 30 days
  it read {commits30} commits across {repos} repositories."
- "Code and price apart": Atlas ranks every subnet by commits in 30
  days and by price change in 7 days; the gap is code rank minus price
  rank, in places out of 100, and 40 or more counts as apart. Copy that
  shows the gap shows the 7-day price beside it, and says "places" or
  "ranks", never "points".
- A statement describes what is on screen. Never pair a picture of one
  ranking with a sentence about another.
- Plain, specific sentences. Digits, not words. No "we". No hype verbs.

## Type

- Archivo only (Google, variable, `wght` and `wdth` axes), loaded with
  `next/font/google` and `axes: ["wdth"]`.
- `font-display`: weight 820, width 92%, tracking -0.04em. The h1 at
  clamp(52px, 6.6vw, 118px), leading 0.9, tracking -0.045em.
- `fig` for large figures: weight 850, width 85%, tracking -0.045em,
  leading 0.86, as in the subnt trader band.
- Text 16 to 22px at 400 to 600; notes 14 to 15px; nothing under 13px.
- The width axis is part of the motion: board names widen to 122% on
  hover, watch-list names to 112%, and the footer wordmark widens from
  62% to 125% as it scrolls in.
- Proportional figures; numeric columns align right.

## Colour

| Role | Dark | Light |
|---|---|---|
| ground | `#0a0a0b` | `#f2f2f0` |
| s1 (panels, the boards field) | `#161618` | `#e7e7e4` |
| s2 (hover) | `#1e1e21` | `#dcdcd8` |
| rule | `#2c2c31` | `#cfcfcb` |
| ink | `#f1f1ef` | `#0d0d0f` |
| ink 2 | `#a3a0a6` | `#48484e` |
| ink 3 | `#8b8890` | `#5b5b61` |
| accent (marks, the action) | `#ff3b30` | `#e0261b` |
| accent 2 (red text), down | `#ff5147` | `#b5150c` |
| up (rises only) | `#3fcf7a` | `#0a6630` |
| band ground / ink | `#f1f1ef` / `#0a0a0b` | `#0d0d0f` / `#f2f2f0` |
| band underline | `#c8170e` | `#ff3b30` |

- The ink is a neutral bone, not a yellow cream (the inspector checks).
- The band inverts the page: a light bar on the dark page, a dark bar on
  the light page, with a 6px red underline.
- The main button is red with dark text in dark, white text in light;
  both pass AA. Every text pair above passes AA (checked by script and
  by Lighthouse `color-contrast` in both schemes).
- Lanes and bar charts on the boards are ink, not accent.

## Width and shape

- Content runs to 1600px, centred, with a gutter of clamp(16px, 4vw,
  64px). The field and the bands run edge to edge.
- Header: one row at every width. 76px from md up, with the four links
  and the block readout; 56px on a phone, with the wordmark and the
  block readout, and the pages in the bottom bar.
- Buttons: solid, radius 3px, 48px tall. Secondary actions: an
  underlined text link. Panels: no border, no shadow; surfaces separate
  by tone. Rules only in tables and lists.

## The home page, in order

1. **The flight.** A Three.js field (one `InstancedMesh`): 128 rows in
   sediment order (no code at the back as dotted lines, then silent,
   then by 30-day commits, busiest at the front) by 90 days, newest on
   the right. Box height and tone follow `log1p(commits)`; head-tier
   rows in red. Flat Lambert shading, no bloom or glow. The days rise
   left to right once on load (1 s). On wide screens a 420vh stage
   holds while the scroll flies the camera through three stops, each
   with a statement that describes what is on screen: "One row for
   every subnet" (the quiet back), "90 days of commits" (how to read a
   mark, and what red means), "Where the code is moving" (the busiest
   front rows, naming the busiest subnet). Pointing lifts a row and a
   tag names it.
   Labels (dates, the today edge with "est. block N", names) are HTML
   projected from 3D. Phones: copy first, then the field as a figure,
   then the three statements as a strip, one per view. A swipe through
   the strip moves the camera between three views made for an upright
   screen (the whole field, low enough to read a mark's height, along
   the busiest rows), and the camera sways slowly on the view it rests
   on. Reduced motion: still, statements stacked. No WebGL: drawn flat.
2. **The band.** The month's commits as a large figure that counts up,
   a proportional bar of who wrote them (opens left to right), and four
   figures with the estimated block. On phones a legend replaces the
   names in the bar.
3. **The lead panel.** The top 3 of the fleet board as tabs that advance
   every 8 s while in view (a red line fills under the tab), until the
   visitor takes over. Each: name, why it ranks, the 7-day price as the
   large figure (30-day beside it), 90 days of commit bars (last 30 in
   red) with a running total, and five figures ending with the gap
   ("Code against price"). Pointing at the chart reads one day.
4. **Next on the board.** Rows 4 to 12, each with five squares (code
   this week, code this month, three or more authors, price up over 30
   days, emission route visible) that fill in green row by row.
5. **Four boards** on the s1 field. Names widen and turn red on hover.
6. **Three columns:** gone cold (days since the last commit), busiest
   this week (green sparklines that draw in), runtime upgrades (gaps
   between specs as bars).
7. **What it reads**, then the footer: the name returns at full width
   and widens as it scrolls in.

## Motion list

1. The flight: load rise, scroll camera, hover lift, the phone's swipe
   camera and sway, the block clock.
2. Once-on-arrival data motion: count-ups, the band bar, the lead
   chart, the squares, the sparklines, the upgrade gaps. Each is the
   data drawing itself, never a fade-up on a section.
3. The lead panel's tab cycle.
4. Width-axis hovers and the footer wordmark.
5. Hover and press feedback: colour, background tone, scale 0.98.

Rules: transform, opacity and stroke only. Server markup is the
finished state; the client arms a start state only below the fold.
Reduced motion keeps every finished state and stops the cycle, the
sway and the flight.

## Engineering notes

- The stage mode (fly, overlay, swipe, still, flat) is decided once, by
  an inline head script that writes `data-flight` on `<html>` before
  first paint from the width (900px), `prefers-reduced-motion` and a
  WebGL probe, and again when one of them changes. The styles and the
  Flight component both read that attribute: no layout jump after
  hydration, and a tablet that turns rebuilds the field in the new mode.
  The rule is `src/state/flight-mode.ts`. Without script the page has no
  mode: copy and statements, no field.
- Every part with states has them named and tested: README, "State
  machines".
- Next 16 keeps pages alive in React Activity: effects re-run on the
  same DOM. The flight creates a fresh canvas per mount, disposes the
  renderer, geometries and materials, and releases the context on
  cleanup.
- Three.js loads with `import("three")` inside the effect, out of the
  first bundle. Versions are pinned exactly.
- Field colours come from `--field-*` CSS variables and repaint on a
  scheme change.

## The phone

Below md the site is its own composition, not the desktop squeezed.

- The pages (Home and the four boards) are a bottom bar in thumb reach:
  a plain bar one tone above the page (s2), text only, 56px plus the
  home-bar inset, the 2px accent line over the page on show. No icons,
  no glass, no pill. The page keeps the same room free at its end.
- The page draws under the notch (`viewport-fit=cover`); the bars and
  the gutters add the safe-area insets.
- Hover is for pointers: every hover style sits behind `(hover: hover)`,
  and every row, tab and button has an `:active` state for a thumb.
  Touch targets are 44px or more.
- Home: the main action is a full-width button, 52px. The lead panel
  runs edge to edge with three equal tabs; a sideways drag across its
  chart reads the days. "Next on the board" rows are two lines: the name
  with its figure, then the last commit with the squares. "What it
  reads" is a list.
- Boards: below 640px a table is a list of rows. Every field stays: the
  name with its key figure, a line of words, then a strip of labelled
  figures. The filter is one row that scrolls sideways inside itself and
  sticks to the top while the list scrolls. The network vitals are a
  list with the figure on the right.

## Boards (mining, fleet, network, upgrades)

- Same tokens and type. Shell: the top bar (the subnt.dev wordmark,
  four links, the block readout on the boards). Each board: an Archivo
  title, one finding sentence, the data age and stale label, then the
  content. Tables with rules, right-aligned numbers, ink activity lanes.
  Filters: text tabs with an accent underline as wide as the label.

## Checks to keep

Lighthouse a11y of 95 or more in both schemes, AA contrast, the reduced
motion check, the first-screen check at 1280x720 and 390x844, the
inspector (home with the allowances above; boards with `--app`) on a
production build, a client-navigation round trip with no WebGL errors,
the fixture scrub and allowlist tests, and operator-free data. At 390px
the inspector also takes `--allow covered-text` (see the rules relaxed).
`npm run check:browser` covers the state machines in a real browser:
the stage mode on a phone, a tablet that turns, reduced motion and a
desktop; the lead panel cycle; links into the fleet board; the filter
keys; and what the phone's bars pass over.
