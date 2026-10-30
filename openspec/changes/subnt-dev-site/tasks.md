# Tasks

## 1. Scaffold web/

- [x] 1.1 Create `web/` with Next.js 16, TypeScript strict, Tailwind v4, shadcn/ui, Motion; add `node_modules/`, `.next/`, `.vercel/`, `web/.env*`, `*.tsbuildinfo` to `.gitignore`; verify `npm run build` passes in `web/`
- [x] 1.2 Add `web/vercel.json` ignoreCommand; use `VERCEL_GIT_PREVIOUS_SHA` and build when unset; verify with dry runs: a diff outside `web/` skips, a diff inside `web/` builds, a multi-commit push with `web/` in an earlier commit builds, an unset SHA builds
- [x] 1.3 Add `COMPONENTS["web"]` and `web/tests`, then run `python3 tools/readme_sync.py`; verify the `web/` row appears and `tools/tests` pass

## 2. Isolation test

- [x] 2.1 Add a test in `upgrade/tests` that the scope gate rejects `web/package.json` and `web/src/app/page.tsx`; verify the upgrade test suite passes

## 3. Data layer and fixtures

- [x] 3.1 Define types and data-layer modules in `web/src/data/` for the four boards; verify `tsc --noEmit` passes
- [x] 3.2 Write the export script in `web/scripts/`: read-only over SSH from `var/fleet/fleet.db` (`mode=ro`) and the `board` JSON, build records from a named field allowlist, round and age values; run it once; verify JSON lands in `web/src/data/fixtures/` with no owner-specific field
- [x] 3.3 Add the scrub test (tokens, addresses outside allowlist, IPs, hostnames) and an allowlist test (a planted extra field is dropped); wire both into `web/package.json` `test`; verify they pass on the fixtures and fail on a planted secret

## 4. Design direction

- [x] 4.1 Run `design-taste-frontend` `draw.mjs` and `ui-ux-pro-max` design-system search; record the chosen direction in `web/DESIGN.md`; verify the owner approved it; the inspector uses `/snap/bin/chromium`
- [x] 4.2 Build the shell: layout, nav, theme tokens, dark mode, reduced-motion handling; verify `inspect.mjs` runs clean on the shell

## 5. Pages

- [x] 5.1 Build the home page; verify `inspect.mjs` and the first-screen check at 1280x720 and 390x844
- [x] 5.2 Build mining triage; verify it renders from fixtures, shows the data age, and shows the stale label past 48 hours
- [x] 5.3 Build fleet attention with rotation signals; verify it renders from fixtures, shows the data age, and shows the stale label past 48 hours
- [x] 5.4 Build network pulse; verify it renders from fixtures, shows the data age, and shows the stale label past 48 hours
- [x] 5.5 Build the runtime-upgrade timeline; verify it renders from fixtures, shows the data age, and shows the stale label past 48 hours

## 6. Ship checks

- [x] 6.1 Run Lighthouse accessibility and a reduced-motion check on every page; verify Lighthouse accessibility >= 95 and no AA contrast failures
- [x] 6.2 Fix the README line that calls subnt.dev retired; verify `python3 tools/readme_sync.py` leaves no diff
- [ ] 6.3 Deploy to a Vercel preview URL (owner action); verify the preview serves the home page. The subnt.dev domain cutover is a later owner step
- [x] 6.4 Capture `web/` `npm test`, `tsc --noEmit`, `npm run build` and Lighthouse output into `docs/greenfield/subnt-dev-site/08-verify.md`, beside the `verify.sh` output
