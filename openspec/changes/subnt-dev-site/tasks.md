# Tasks

## 1. Scaffold web/

- [ ] 1.1 Create `web/` with Next.js 16, TypeScript strict, Tailwind v4, shadcn/ui, Motion; verify `npm run build` passes in `web/`
- [ ] 1.2 Add `web/vercel.json` ignoreCommand; verify with a dry run that a diff outside `web/` exits to skip and a diff inside `web/` builds
- [ ] 1.3 Add `web/` row via `python3 tools/readme_sync.py`; verify `tools/tests` pass

## 2. Isolation test

- [ ] 2.1 Add a test in `upgrade/tests` that the scope gate rejects `web/package.json` and `web/src/app/page.tsx`; verify the upgrade test suite passes

## 3. Data layer and fixtures

- [ ] 3.1 Define types and data-layer modules in `web/src/data/` for the four boards; verify `tsc --noEmit` passes
- [ ] 3.2 Write the export script in `web/scripts/` and run it once against the live stores; verify JSON lands in `web/src/data/fixtures/`
- [ ] 3.3 Add the scrub test (tokens, addresses outside allowlist, IPs, hostnames); verify it passes on the fixtures and fails on a planted secret

## 4. Design direction

- [ ] 4.1 Run `design-taste-frontend` `draw.mjs` and `ui-ux-pro-max` design-system search; record the chosen direction in `web/DESIGN.md`; verify the owner approved it
- [ ] 4.2 Build the shell: layout, nav, theme tokens, dark mode, reduced-motion handling; verify `inspect.mjs` runs clean on the shell

## 5. Pages

- [ ] 5.1 Build the home page; verify `inspect.mjs` and a first-screen check against the home spec scenario
- [ ] 5.2 Build mining triage; verify it renders from fixtures with a data-age label
- [ ] 5.3 Build fleet attention with rotation signals; verify as above
- [ ] 5.4 Build network pulse; verify as above
- [ ] 5.5 Build the runtime-upgrade timeline; verify as above

## 6. Ship checks

- [ ] 6.1 Run Lighthouse accessibility and a reduced-motion check on every page; verify no failures
- [ ] 6.2 Fix the README line that calls subnt.dev retired; verify `python3 tools/readme_sync.py` leaves no diff
- [ ] 6.3 Deploy to Vercel for subnt.dev (owner action); verify the live URL serves the home page
