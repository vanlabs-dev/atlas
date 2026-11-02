# subnt.dev design

Approved: 2026-11-02 (owner, comp D "Flight and instrument"). It
replaces comp F, "Strata as an instrument" (2026-10-30), across the
whole site.

Reference comp: `docs/explore/home-motion/d-combined.html` on branch
`explore/home-motion`, with the picker `index.html` beside it (real
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
  chain and market, from one Raspberry Pi at home. In the last 30 days
  it read {commits30} commits across {repos} repositories."
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
   with a statement: the quiet back, the run along 90 days to today,
   the busiest rows up close. Pointing lifts a row and a tag names it.
   Labels (dates, the today edge with "est. block N", names) are HTML
   projected from 3D. Phones: copy first, the field as a figure with a
   slow sway. Reduced motion: still. No WebGL: drawn flat.
2. **The band.** The month's commits as a large figure that counts up,
   a proportional bar of who wrote them (opens left to right), and four
   figures with the estimated block. On phones a legend replaces the
   names in the bar.
3. **The lead panel.** The top 3 of the fleet board as tabs that advance
   every 8 s while in view (a red line fills under the tab), until the
   visitor takes over. Each: name, why it ranks, price over 30 days, 90
   days of commit bars (last 30 in red) with a running total, five
   figures. Pointing at the chart reads one day.
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

1. The flight: load rise, scroll camera, hover lift, phone sway, the
   block clock.
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

- The stage mode is decided in CSS (`min-width: 900px` and
  `prefers-reduced-motion`), plus an inline head script that adds
  `nogl` to `<html>` before first paint. No layout jump after hydration.
- Next 16 keeps pages alive in React Activity: effects re-run on the
  same DOM. The flight creates a fresh canvas per mount, disposes the
  renderer, geometries and materials, and releases the context on
  cleanup.
- Three.js loads with `import("three")` inside the effect, out of the
  first bundle. Versions are pinned exactly.
- Field colours come from `--field-*` CSS variables and repaint on a
  scheme change.

## Boards (mining, fleet, network, upgrades)

- Same tokens and type. Shell: the top bar (wordmark with a red period,
  four links, the block readout on the boards). Each board: an Archivo
  title, one finding sentence, the data age and stale label, then the
  content. Tables with rules, right-aligned numbers, ink activity lanes.
  Filters: text tabs with an accent underline as wide as the label.

## Checks to keep

Lighthouse a11y of 95 or more in both schemes, AA contrast, the reduced
motion check, the first-screen check at 1280x720 and 390x844, the
inspector (home with the allowances above; boards with `--app`) on a
production build, a client-navigation round trip with no WebGL errors,
the fixture scrub and allowlist tests, and operator-free data.
