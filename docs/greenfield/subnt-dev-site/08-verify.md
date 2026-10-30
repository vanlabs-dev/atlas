# subnt-dev-site: verify

Date: 2026-10-30. Session 4, second run, after the Strata restyle. This
file replaces the first run, which verified the rejected "One motif"
build. All output below is from build `f07c4ce`, served with `next start`
on port 3100.

Result: PASS. `verify.sh` exits 0, and every spec check below passes.
The design inspector still reports 7 FAIL on the home page; each one is
a choice in the approved design, listed under "Design gate". Task 6.3
(Vercel preview) is an owner action and is still open.

## Fixtures

Exported 2026-10-30 by `web/scripts/export-fixtures.ts`, read-only over
SSH. Mining, network and upgrades are cut off 7 days before the export
and rounded to 4 significant digits. The fleet board is a same-hour
snapshot (`generatedAt` 2026-10-29 23:43 UTC): `build_board` reads the
latest pass and ignores the cutoff, and its values are rounded, not
aged. The new `daily` series (90 days per subnet) is binned back from
each subnet's latest activity pass, the instant the fleet board reads,
so a test can check its 7- and 30-day sums against the board.

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

✔ fixtures exist (1.285775ms)
✔ fleet.json has no leaks (0.942738ms)
✔ fleet.json has no em dash (0.226537ms)
✔ mining.json has no leaks (0.578792ms)
✔ mining.json has no em dash (0.115067ms)
✔ network.json has no leaks (0.348207ms)
✔ network.json has no em dash (0.061336ms)
✔ upgrades.json has no leaks (0.144913ms)
✔ upgrades.json has no em dash (0.0532ms)
✔ scrub catches planted leaks (0.168798ms)
✔ allowlist drops unlisted fields (0.19608ms)
✔ allowlist rounds and strips em dashes (0.084279ms)
✔ allowlist rejects nested values (0.147558ms)
✔ allowlist accepts only a 90-day integer series (0.172906ms)
✔ daily series cover 128 subnets and match the board counts (0.604421ms)
✔ fresh under 48 hours (0.598189ms)
✔ stale past 48 hours (0.087455ms)
✔ future timestamps read as now (0.072597ms)
ℹ tests 18
ℹ suites 0
ℹ pass 18
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 65.758806
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
✓ Running next.config.ts took 16ms
- Cache Components enabled
- Partial Prefetching enabled
  Creating an optimized production build ...
✓ Compiled successfully in 190ms
  Running TypeScript ...
  Finished TypeScript in 948ms ...
  Collecting page data using 9 workers ...
  Generating static pages using 9 workers (0/8) ...
  Generating static pages using 9 workers (2/8) 
  Generating static pages using 9 workers (4/8) 
  Generating static pages using 9 workers (6/8) 
✓ Generating static pages using 9 workers (8/8) in 441ms
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
strata seal line runs on `requestAnimationFrame`, so on the home page the
check also counts animation frames across one full 12 s block. The
control run (motion allowed) must fail, and does: 38 frames.

```
OK   /          reduce=true css=[] canvasFrames=0
OK   /mining    reduce=true css=[] canvasFrames=0
OK   /fleet     reduce=true css=[] canvasFrames=0
OK   /network   reduce=true css=[] canvasFrames=0
OK   /upgrades  reduce=true css=[] canvasFrames=0
exit 0
--- control (motion allowed, must FAIL)
FAIL /          reduce=false css=[] canvasFrames=38
exit 1
```

## First screen and data age

Home at 1280x720 and 390x844: the h1, the sentence under it and links to
the four boards are in view without scrolling. Each board shows its data
time, and the stale label exactly when the data is over 48 hours old.

```
OK   home 1280x720 h1=true sentence=true links=[true,true,true,true]
OK   home 390x844 h1=true sentence=true links=[true,true,true,true]
OK   /mining    Data from 22 Oct 2026, 23:33 UTC, 7 days ago | 169 h, stale label true
OK   /fleet     Data from 29 Oct 2026, 23:43 UTC, under an hour ago | 0 h, stale label false
OK   /network   Data from 22 Oct 2026, 23:43 UTC, 7 days ago | 168 h, stale label true
OK   /upgrades  Data from 22 Oct 2026, 23:43 UTC, 7 days ago | 168 h, stale label true
exit 0
```

## Design gate

`design-taste-frontend` inspector and lint. The local direction sheet
(`web/.taste-skill/direction.json`, gitignored) still held the rejected
"One motif" type (General Sans); it now marks type as kept from
DESIGN.md, which clears `font-not-dealt`. Lint lines that DESIGN.md
asks for (table rules, underlined text links, the 1px tab line) carry a
same-line `taste-skill-ignore` with the reason.

```
### inspect.mjs /
  [headline-lines] @1440px  1 headline(s) wrap past two lines at 1440px: "Atlas reads all 128 Bittensor subnets." → 3 lines (6 words, 95px)
  [few-pictures] @1440px  Only 0 picture(s) on the page (0 photographs, footage or raster images, 0 interface fragments). Drawings in SVG do not count.
  [still-page] @1440px  Only 1 element(s) moved while the page loaded and scrolled.
  [headline-lines] @768px  1 headline(s) wrap past two lines at 768px: "Atlas reads all 128 Bittensor subnets." → 3 lines (6 words, 50.7px)
  [headline-lines] @390px  1 headline(s) wrap past two lines at 390px: "Atlas reads all 128 Bittensor subnets." → 3 lines (6 words, 48px)
  [eyebrow] @390px  1 eyebrow/kicker label(s) above headings: "Open the fleet board" above "Cathedral"
  [off-centre] @390px  The page sits off-centre: its content comes to 16px from the left edge but only to 101px from the right, at 390px.
  [size-count] @1440px (+768, 390)  12 different font sizes (13, 15, 16, 18, 20, 22, 24, 32, 40, 63, 64, 95).
  [no-footage] @1440px  No video anywhere on the page.
  [off-centre] @1440px (+768)  The margins differ: 92px on the left, 114px on the right, at 1440px.
  [side-scroll] @390px  1 row(s) scroll sideways with content past their edge.
RESULT: 7 FAIL, 4 WARN - not done.
### inspect.mjs --app /mining
  [app-title-size] @1440px (+768, 390)  The h1 is 63px ("Mining triage").
  [kpi-size] @1440px  A figure is set at 64px.
RESULT: 0 FAIL, 2 WARN - measurements pass. Passing the meter is the floor, not the grade: score the screenshots with references/critique.md.
### inspect.mjs --app /fleet
  [app-title-size] @1440px (+768, 390)  The h1 is 63px ("Fleet attention").
  [kpi-size] @1440px  A figure is set at 64px.
RESULT: 0 FAIL, 2 WARN - measurements pass. Passing the meter is the floor, not the grade: score the screenshots with references/critique.md.
### inspect.mjs --app /network
  [app-title-size] @1440px (+768, 390)  The h1 is 63px ("Network pulse").
  [kpi-size] @1440px  A figure is set at 56px.
RESULT: 0 FAIL, 2 WARN - measurements pass. Passing the meter is the floor, not the grade: score the screenshots with references/critique.md.
### inspect.mjs --app /upgrades
  [app-title-size] @1440px (+768, 390)  The h1 is 63px ("Runtime upgrades").
  [kpi-size] @1440px  A figure is set at 64px.
RESULT: 0 FAIL, 2 WARN - measurements pass. Passing the meter is the floor, not the grade: score the screenshots with references/critique.md.
### lint.mjs src
RESULT: 0 FAIL, 0 WARN
```

Home FAILs kept, each a choice in the approved comp E:

- `headline-lines` (x3): the h1 is the approved copy at the approved
  size, "Atlas reads all 128 Bittensor subnets.", and it sets in three
  lines at every width, as in the comp. Two lines need a smaller h1 or
  new copy. Owner call.
- `few-pictures`, `no-footage`: the picture is the strata canvas, which
  the inspector does not count. The comp has no photographs.
- `still-page`: DESIGN.md allows three motions only (block tick, hover,
  panel swap) and no entrance animations.
- `eyebrow` at 390: false read. It pairs the hero button with the panel
  title below it. The panel's own label was folded into its sentence.
- `off-centre` at 390: the panel closes the right margin at 16 px (see
  `mobile-fold.jpg`); the short side is the ragged right of the copy.

Board warnings kept: `app-title-size` and `kpi-size` are DESIGN.md's
Newsreader titles (clamp to 64 px) and large figures (64 px).

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

Screenshots at 1440, 768 and 390, light and dark:

- Strong: the strata field is real data (9,779 commits in 30 days across
  104 repositories) and carries the idea at once. The boards share one
  type system and read as one product.
- Weak: on the fleet board at 1280 px the longer "why it ranks" values
  wrap to two lines, and the table scrolls sideways to reach the lane. The 7-day-old fixtures show the stale label on
  three boards, which is correct but reads as broken until live data
  lands.
