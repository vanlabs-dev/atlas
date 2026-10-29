# subnt-dev-site: verify

Date: 2026-10-30. Session 4. All output below is from the final build
(commit before this file), served with `next start` on port 3100.

Result: PASS. `verify.sh` exits 0, and every `web/` check below passes.
Task 6.3 (Vercel preview) is an owner action and is still open.

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
✔ fixtures exist (0.804055ms)
✔ fleet.json has no leaks (0.688088ms)
✔ fleet.json has no em dash (0.167554ms)
✔ mining.json has no leaks (0.529531ms)
✔ mining.json has no em dash (0.12792ms)
✔ network.json has no leaks (0.347089ms)
✔ network.json has no em dash (0.047178ms)
✔ upgrades.json has no leaks (0.100158ms)
✔ upgrades.json has no em dash (0.054432ms)
✔ scrub catches planted leaks (0.169527ms)
✔ allowlist drops unlisted fields (0.17618ms)
✔ allowlist rounds and strips em dashes (0.077465ms)
✔ allowlist rejects nested values (0.137688ms)
✔ fresh under 48 hours (0.442117ms)
✔ stale past 48 hours (0.082134ms)
✔ future timestamps read as now (0.071855ms)
ℹ tests 16
ℹ suites 0
ℹ pass 16
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 62.453557
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
✓ Running next.config.ts took 15ms
- Cache Components enabled
- Partial Prefetching enabled
  Creating an optimized production build ...
✓ Compiled successfully in 230ms
  Running TypeScript ...
  Finished TypeScript in 1146ms ...
  Collecting page data using 9 workers ...
  Generating static pages using 9 workers (0/8) ...
  Generating static pages using 9 workers (2/8) 
  Generating static pages using 9 workers (4/8) 
  Generating static pages using 9 workers (6/8) 
✓ Generating static pages using 9 workers (8/8) in 420ms
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
`color-contrast` is the WCAG AA text-contrast audit.

```
scheme   page      a11y  failing audits
light    home      100   none | color-contrast: 1
light    mining    100   none | color-contrast: 1
light    fleet     100   none | color-contrast: 1
light    network   100   none | color-contrast: 1
light    upgrades  100   none | color-contrast: 1
dark     home      100   none | color-contrast: 1
dark     mining    100   none | color-contrast: 1
dark     fleet     100   none | color-contrast: 1
dark     network   100   none | color-contrast: 1
dark     upgrades  100   none | color-contrast: 1
dark browser check (prefers dark, body background): 9334 [true,"rgb(19, 54, 33)"]
```

## Reduced motion

Each page loaded with `prefers-reduced-motion: reduce`, scrolled, then
checked for animations longer than an instant and for hidden entrances. A
control run without reduced motion catches the hero `shutter` and `settle`
animations, so the check can fail.

```
OK   /          reduce=true running=[] hidden=0
OK   /mining    reduce=true running=[] hidden=0
OK   /fleet     reduce=true running=[] hidden=0
OK   /network   reduce=true running=[] hidden=0
OK   /upgrades  reduce=true running=[] hidden=0
exit 0
```

## First screen and data age

Home at 1280x720 and 390x844: the h1, the sentence under it and links to
the four boards are in view without scrolling. Each board shows its data
time, and the stale label exactly when the data is over 48 hours old.

```
OK   home 1280x720 h1=true sentence=true links=[true,true,true,true]
OK   home 390x844 h1=true sentence=true links=[true,true,true,true]
OK   /mining    Data from 22 Oct 2026, 17:25 UTC, 7 days ago | 174 h, stale label true
OK   /fleet     Data from 29 Oct 2026, 22:31 UTC, under an hour ago | 1 h, stale label false
OK   /network   Data from 22 Oct 2026, 22:31 UTC, 7 days ago | 169 h, stale label true
OK   /upgrades  Data from 22 Oct 2026, 22:31 UTC, 7 days ago | 169 h, stale label true
exit 0
```

## Design gate

`design-taste-frontend` inspector and lint on the final build.

```
### inspect.mjs /
  [no-real-pictures] @1440px  Only 0 real photograph(s) or clip(s); the rest are interface fragments.
  [no-footage] @1440px  No video anywhere on the page.
  [untitled-section] @1440px  A section carries text but no heading: div.mx-auto.max-w-[1440px] at 900px.
  [still-page] @1440px  Little motion: 13 element(s) moved while the page loaded and scrolled.
RESULT: 0 FAIL, 4 WARN - measurements pass. Passing the meter is the floor, not the grade: score the screenshots with references/critique.md.
### inspect.mjs --app /mining
  [unused-canvas] @1440px  The content stops 371px short of the right edge while it starts 64px from the sidebar.
  [ragged-row] @1440px  1 pair(s) of cards in one row end at different heights (by 5060px).
RESULT: 0 FAIL, 2 WARN - measurements pass. Passing the meter is the floor, not the grade: score the screenshots with references/critique.md.
### inspect.mjs --app /fleet
  [ragged-row] @1440px  1 pair(s) of cards in one row end at different heights (by 336px).
RESULT: 0 FAIL, 1 WARN - measurements pass. Passing the meter is the floor, not the grade: score the screenshots with references/critique.md.
### inspect.mjs --app /network
  [panel-void] @1440px  2 card(s) hold a blank band inside: 82px in "Emission gate", 45px in "Chain parameter changes".
RESULT: 0 FAIL, 1 WARN - measurements pass. Passing the meter is the floor, not the grade: score the screenshots with references/critique.md.
### inspect.mjs --app /upgrades
  [unused-canvas] @1440px  The content stops 213px short of the right edge while it starts 64px from the sidebar.
RESULT: 0 FAIL, 1 WARN - measurements pass. Passing the meter is the floor, not the grade: score the screenshots with references/critique.md.
### lint.mjs src
RESULT: 0 FAIL, 0 WARN
```

Warnings kept, with reasons:

- `no-real-pictures`, `no-footage`: the subject is software, so its
  pictures are its own interface fragments (four on the home page). The
  open collections were not searched because downloads need owner
  approval. A Pi photograph or clip is a possible follow-up.
- `untitled-section`: the flagged wrapper holds the showcase section,
  which has its own h2 ("The four boards").
- `still-page`: 13 elements move; the fail line is 8.
- `ragged-row`, `unused-canvas`, `panel-void`: side columns on the boards
  are shorter than the main table by design; stretching them leaves a
  blank band instead.

## Isolation and repo checks

```
> upgrade/tests: python3 -m unittest discover -s .
Ran 37 tests in 0.125s
OK
exit 0
> tools/tests and readme_sync --check
Ran 3 tests in 0.003s
OK
README.md is current
> out-of-scope surface grep (login, password, wallet connect, buy, sell, chat) in web/src
matches above, if any
```

Vercel ignored-build dry runs (task 1.2), scratch repo: diff outside
`web/` skips; diff inside `web/` builds; multi-commit push with `web/` in
an earlier commit builds; unset SHA builds; SHA missing from the clone
builds.

## Look round

Critique of the final screenshots (1440, 768, 390; light and dark):

- Strong: the first screen states what Atlas is in two lines, and the
  live subnet field carries the idea. Dark bottle green and gold read as
  one system across the page and the boards.
- Weak: the how-it-works fields leave tall empty space above each card on
  desktop. The showcase square crops long fragments. There are no real
  photographs.
- Not done: no scroll scenes were dealt, so `scenes.mjs` was not run.
