# subnt-dev-site: verify

Date: 2026-10-30. Session 4, third run, after the comp F rebuild ("Strata
as an instrument"). This file replaces the two earlier runs, which
verified the rejected "One motif" build and the first Strata build. All
output below is from build `c11b301`, served with `next start` on port
3101.

Result: PASS. `verify.sh` exits 0, every spec check passes, and the
design inspector reports 0 FAIL on every page. Task 6.3 (Vercel preview)
is an owner action and is still open.

## Fixtures

Exported 2026-10-30 by `web/scripts/export-fixtures.ts`, read-only over
SSH. Mining, network and upgrades are cut off 7 days before the export
and rounded to 4 significant digits. The fleet board is a same-hour
snapshot (`generatedAt` 2026-10-29 23:43 UTC): `build_board` reads the
latest pass and ignores the cutoff, and its values are rounded, not
aged. The `daily` series (90 days per subnet) is binned back from each
subnet's latest activity pass, the instant the fleet board reads, so a
test checks its 7- and 30-day sums against the board.

## verify.sh

`bash ~/.claude/skills/greenfield/scripts/verify.sh subnt-dev-site .`

`verify.sh` runs nothing in `web/` (review finding 6), so the `web/`
checks are captured by hand in the sections after it.

```
=== greenfield verify: subnt-dev-site ===
Project root: /home/van/src/github/vanlabs-dev/atlas
Artifact dir: /home/van/src/github/vanlabs-dev/atlas/docs/greenfield/subnt-dev-site

Checking greenfield artifacts...
  OK  01-brainstorm.md
  OK  07-review.md
  note  09-ship.md not present yet

Checking OpenSpec change...
  OK  openspec/changes/subnt-dev-site

Running project checks (if present)...

RESULT: PASS
verify.sh exit 0
```

## web/: npm test

```

> web@0.1.0 test
> node --test 'tests/**/*.test.ts'

✔ fixtures exist (0.743971ms)
✔ fleet.json has no leaks (0.924238ms)
✔ fleet.json has no em dash (0.226323ms)
✔ mining.json has no leaks (0.552473ms)
✔ mining.json has no em dash (0.113252ms)
✔ network.json has no leaks (0.360334ms)
✔ network.json has no em dash (0.052839ms)
✔ upgrades.json has no leaks (0.145952ms)
✔ upgrades.json has no em dash (0.072836ms)
✔ scrub catches planted leaks (0.276006ms)
✔ allowlist drops unlisted fields (0.208059ms)
✔ allowlist rounds and strips em dashes (0.089237ms)
✔ allowlist rejects nested values (0.174927ms)
✔ allowlist accepts only a 90-day integer series (0.255157ms)
✔ daily series cover 128 subnets and match the board counts (0.811437ms)
✔ fresh under 48 hours (0.43876ms)
✔ stale past 48 hours (0.085059ms)
✔ future timestamps read as now (0.069019ms)
ℹ tests 18
ℹ suites 0
ℹ pass 18
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 73.897431
exit 0
```

## web/: tsc --noEmit and eslint

```

> web@0.1.0 typecheck
> tsc --noEmit

exit 0
> npx eslint src
exit 0
```

## web/: npm run build

```
> web@0.1.0 build
> next build
▲ Next.js 16.4.3 (Turbopack)
✓ Running next.config.ts took 14ms
- Cache Components enabled
- Partial Prefetching enabled
  Creating an optimized production build ...
✓ Compiled successfully in 227ms
  Running TypeScript ...
  Finished TypeScript in 952ms ...
  Collecting page data using 9 workers ...
  Generating static pages using 9 workers (0/8) ...
  Generating static pages using 9 workers (2/8) 
  Generating static pages using 9 workers (4/8) 
  Generating static pages using 9 workers (6/8) 
✓ Generating static pages using 9 workers (8/8) in 483ms
  Finalizing page optimization ...
Route (app)
┌ ○ /
├ ○ /_not-found
├ ○ /fleet
├ ○ /mining
├ ○ /network
└ ○ /upgrades
○  (Static)  prerendered as static content
exit 0
```

## Lighthouse accessibility

Lighthouse 12 attached to headless Chromium (`/snap/bin/chromium`), one
browser per scheme; the dark browser runs with `--force-dark-mode`.
`color-contrast` is the WCAG AA text-contrast audit. Script:
`~/scratch/2026-10-30-subnt-dev-site/checks/lighthouse.sh`.

```
scheme   page      a11y  failing audits
light browser check: 9301 [false,"rgb(246, 247, 248)"]
light    home      100   none | color-contrast: 1
light    mining    100   none | color-contrast: 1
light    fleet     100   none | color-contrast: 1
light    network   100   none | color-contrast: 1
light    upgrades  100   none | color-contrast: 1
dark browser check: 9302 [true,"rgb(8, 9, 10)"]
dark     home      100   none | color-contrast: 1
dark     mining    100   none | color-contrast: 1
dark     fleet     100   none | color-contrast: 1
dark     network   100   none | color-contrast: 1
dark     upgrades  100   none | color-contrast: 1
```

## Reduced motion

Each page loaded with `prefers-reduced-motion: reduce`, scrolled, then
checked for CSS animations or transitions longer than an instant. The
strata's load replay, block flare and idle tour all run on
`requestAnimationFrame`, so on the home page the check also counts
animation frames across one full 12 s block. The control run (motion
allowed) must fail, and does: the replay and the idle tour draw 818
frames.

```
OK   /          reduce=true css=[] canvasFrames=0
OK   /mining    reduce=true css=[] canvasFrames=0
OK   /fleet     reduce=true css=[] canvasFrames=0
OK   /network   reduce=true css=[] canvasFrames=0
OK   /upgrades  reduce=true css=[] canvasFrames=0
exit 0
--- control (motion allowed, must FAIL)
FAIL /          reduce=false css=[] canvasFrames=818
exit 1
```

## First screen and data age

Home at 1280x720 and 390x844: the h1, the sentence under it and links to
the four boards are in view without scrolling. Each board shows its data
time, and the stale label exactly when the data is over 48 hours old.

```
OK   home 1280x720 h1=true sentence=true links=[true,true,true,true]
OK   home 390x844 h1=true sentence=true links=[true,true,true,true]
OK   /mining    Data from 22 Oct 2026, 23:33 UTC, 7 days ago | 170 h, stale label true
OK   /fleet     Data from 29 Oct 2026, 23:43 UTC, 1 h ago | 2 h, stale label false
OK   /network   Data from 22 Oct 2026, 23:43 UTC, 7 days ago | 170 h, stale label true
OK   /upgrades  Data from 22 Oct 2026, 23:43 UTC, 7 days ago | 170 h, stale label true
exit 0
```

## Design gate

`design-taste-frontend` inspector and lint. `headline-lines`,
`few-pictures` and `still-page` are relaxed for Strata (DESIGN.md,
owner, 2026-10-30). The local direction sheet
(`web/.taste-skill/direction.json`, gitignored) marks type as kept from
DESIGN.md. Lint lines that DESIGN.md asks for (table rules, underlined
text links, the 1px tab line, the one hero scrim) carry a same-line
`taste-skill-ignore` with the reason.

```
### inspect.mjs / --allow headline-lines,few-pictures,still-page
  [hairline] @1440px  1 thin rule(s)/divider line(s): span.lead 13px
  [size-count] @1440px (+768, 390)  11 different font sizes (13, 16, 20, 22, 24, 28, 32, 40, 63, 64, 92).
  [grey-body] @1440px (+768, 390)  The running text is a soft grey on its ground (5.7:1).
  [no-footage] @1440px  No video anywhere on the page.
  [side-scroll] @768px (+390)  1 row(s) scroll sideways with content past their edge.
  [off-centre] @768px  The margins differ: 31px on the left, 62px on the right, at 768px.
RESULT: 0 FAIL, 6 WARN - measurements pass. Passing the meter is the floor, not the grade: score the screenshots with references/critique.md.
### inspect.mjs --app /mining
  [tabular] @1440px (+768, 390)  Only 0% of the figures use tabular numerals.
  [app-title-size] @1440px (+768, 390)  The h1 is 63px ("Mining triage").
  [kpi-size] @1440px  A figure is set at 64px.
RESULT: 0 FAIL, 3 WARN - measurements pass. Passing the meter is the floor, not the grade: score the screenshots with references/critique.md.
### inspect.mjs --app /fleet
  [tabular] @1440px (+768, 390)  Only 0% of the figures use tabular numerals.
  [app-title-size] @1440px (+768, 390)  The h1 is 63px ("Fleet attention").
  [kpi-size] @1440px  A figure is set at 64px.
RESULT: 0 FAIL, 3 WARN - measurements pass. Passing the meter is the floor, not the grade: score the screenshots with references/critique.md.
### inspect.mjs --app /network
  [tabular] @1440px (+768, 390)  Only 0% of the figures use tabular numerals.
  [app-title-size] @1440px (+768, 390)  The h1 is 63px ("Network pulse").
  [kpi-size] @1440px  A figure is set at 64px.
RESULT: 0 FAIL, 3 WARN - measurements pass. Passing the meter is the floor, not the grade: score the screenshots with references/critique.md.
### inspect.mjs --app /upgrades
  [tabular] @1440px (+768, 390)  Only 0% of the figures use tabular numerals.
  [app-title-size] @1440px (+768, 390)  The h1 is 63px ("Runtime upgrades").
  [kpi-size] @1440px  A figure is set at 64px.
RESULT: 0 FAIL, 3 WARN - measurements pass. Passing the meter is the floor, not the grade: score the screenshots with references/critique.md.
### lint.mjs src
RESULT: 0 FAIL, 0 WARN
```

Warnings kept, with reasons:

- `tabular` (boards): no tabular figures, on purpose. Schibsted's
  tabular set gives the comma and the point a full figure width
  (DESIGN.md, Type).
- `app-title-size`, `kpi-size`: DESIGN.md's 64px Newsreader titles and
  figures.
- `hairline` (home): the annotation's leader line, an instrument part.
- `size-count`, `grey-body`, `no-footage`: accepted.
- `side-scroll` at 768 and 390: the home fleet table scrolls to reach
  its activity lane.
- `off-centre` at 768 (WARN): the field and its gutter are full-bleed.

Fixed in this run from the inspector: the "Subnet 94" kicker above the
annotation name (folded into the sentence), a ring shadow on the pointer
tag, labels within 16px of the screen edge, the block readout reading as
a kicker over the h1 at 768, and the annotation landing on the copy
below 1024px (tablets now use the stacked layout).

## Isolation and repo checks

```
> upgrade/tests: python3 -m unittest discover -s .
Ran 37 tests in 0.124s
OK
exit 0
> tools/tests and readme_sync --check
Ran 3 tests in 0.003s
OK
README.md is current
exit 0
> out-of-scope surface grep (login, password, wallet connect, buy, sell, chat) in web/src
matches above, if any
```

Vercel ignored-build dry runs (task 1.2) are unchanged from the first
run: diff outside `web/` skips; diff inside `web/` builds; multi-commit
push with `web/` in an earlier commit builds; unset SHA builds.

## Look round

Checked in a real browser at 1440 (dark and light), 768 and 390:

- Strong: the field has a shape (quiet top, busy floor) and reads as a
  chart: dated axis, today edge with the block clock, named rows in the
  margin. The pointer tag, lit row and annotation say what is under the
  cursor; idle, the ghost tour does it unprompted. Tables no longer wrap
  or overflow at 1440.
- Weak: on phones and tablets the field is a figure without margin
  labels or a tour, so it explains less there. The 7-day-old fixtures
  show the stale label on three boards until live data lands.

## Final verify run (2026-10-31, after 46921cd and Vercel preview)

Preview https://atlas-nine-gold.vercel.app/ returns 200 and serves the home page (task 6.3).

```
=== greenfield verify: subnt-dev-site ===
Project root: /home/van/src/github/vanlabs-dev/atlas
Artifact dir: /home/van/src/github/vanlabs-dev/atlas/docs/greenfield/subnt-dev-site

Checking greenfield artifacts...
  OK  01-brainstorm.md
  OK  07-review.md
  note  09-ship.md not present yet

Checking OpenSpec change...
  OK  openspec/changes/subnt-dev-site

Running project checks (if present)...

RESULT: PASS
```
