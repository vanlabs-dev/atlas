# subnt.dev design

Chosen 2026-10-30 at task 4.1 of the `subnt-dev-site` change. Approved by
the owner the same day. Dealt with `design-taste-frontend`; the sheets are
reprinted with `node ~/.claude/skills/design-taste-frontend/scripts/draw.mjs --show`
(working files in `.taste-skill/`, not committed).

## Home page: One motif

- Direction `one-motif`, seed 1003367883, sector dev-tool, tone technical.
- Idea: on this page, the subnet slots Atlas clones and scores become the
  one motif, a square cell. The hero is a field of cells tinted by Atlas's
  own fleet tier. The cell returns as the button, the list bullet and one
  full-width band.
- Live thing: pick a subnet (a cell, or its number) and see its row on all
  four boards. It works without script as plain links.
- Hero: "Fragment on a shaped stage". Sections: showcase (object on a
  disc, here the cell), how-it-works (one card, four fields), list
  (statement, table pushed right), about (inset panel), footer (the mark,
  built large).
- Signature motion: shutter on the hero stage. Section entrances, control
  feedback. All of it drops under `prefers-reduced-motion`.

## Data boards: Data terminal

- App style `data-terminal`, seed 1194055999, kind markets, palette and
  type kept from the home page.
- The move: every selection is a 1px gold line as wide as its label.
  Numbers stay ink or muted and carry their sign in the text.
- Face: the gold accent line from the palette, and the cell field as the
  signature element on the fleet board.
- Shell: icon rail with tooltips and accessible names; a bottom bar on a
  phone.
- Each board leads with its one question and one finding, shows its data
  age, and shows a stale label past 48 hours.

## Type

General Sans (Fontshare), 400, 500, 700. One family. Display 700,
tracking -0.02em, leading 0.9. Text 400, leading 1.45. Tabular figures on
every number. No monospace.

## Colour

| Role | Dark (default) | Light |
|---|---|---|
| ground | `#133621` | `#f3f6ef` |
| surface | `#1a4429` | `#e4ebdf` |
| card (boards) | `#0e2a19` | `#ffffff` |
| ink | `#f4d96c` | `#133621` |
| muted | `#c0b26a` | `#4d5a3c` |
| accent | `#f4d96c` | `#133621` |
| accent ink | `#133621` | `#f4d96c` |

Bottle green ground, gold type. Under 3% colour on board screens beyond
the ink. Text meets WCAG AA in both schemes.

## Rejected

`ui-ux-pro-max` recommended glassmorphism and Fira Code. Both break the
house rules (no glass, no monospace). Kept from it: label data with its
update time and a stale state, and render a static final frame under
reduced motion.
