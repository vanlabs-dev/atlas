# Design

## Context

See proposal.md. Atlas is Python, run on a LAN-only Pi. `web/` is the first
Node code in the repo. The upgrade job pushes to `main` every time the
runtime moves, so deploys must key on `web/` changes. Brainstorm:
`docs/greenfield/subnt-dev-site/01-brainstorm.md`.

## Goals / Non-Goals

**Goals:**
- A distinct, designed site on typed fixtures, shipped page by page.
- A seam so real data later replaces fixtures in one place.

**Non-Goals:**
- Any data pipeline, Supabase client, or auth.
- Server-side revalidation tuning (comes with real data).

## Decisions

- **Next.js 16, App Router, TypeScript strict.** Current stable; 15 gains
  nothing. Static render for now.
- **Data layer `web/src/data/`.** One module per board exposes async
  functions returning types from `types.ts`. Fixtures live in
  `web/src/data/fixtures/*.json`. Alternative: inline fixtures per page,
  rejected, it defeats the swap seam.
- **Fixtures from a one-off export, built by field allowlist.** The
  site is public, so data is operator-free. A script under `web/scripts/`
  reads the Pi's `var/fleet/fleet.db` (opened `mode=ro` over SSH) and the
  `atlas_fleet_dashboard.py board` JSON. It builds each record from a
  named field allowlist, so unknown fields cannot flow. Owner-specific
  fields (holdings, hotkeys, rotation decisions) are never on the list.
  Values are rounded and aged, not live. A test is a second check: it fails
  on token-shaped strings, SS58 addresses outside the public allowlist,
  IPs, and hostnames. `web/package.json` `test` runs it. Alternative: hand-written,
  rejected by the owner for realism.
- **Visual direction decided at apply.** Run `draw.mjs`, record the chosen
  direction in `web/DESIGN.md`, build the home page first, then the others.
  Inspector uses `/snap/bin/chromium`.
- **Isolation.** `upgrade/allowed_paths.py` is unchanged: `web/` is not in
  `ALLOWED`. Add a test in `upgrade/tests` asserting the gate rejects
  `web/` paths. `web/vercel.json` `ignoreCommand` diffs against
  `VERCEL_GIT_PREVIOUS_SHA` and builds when it is unset, so a multi-commit
  push with `web/` in an earlier commit still builds.
- **Deploy.** Preview URL first. The subnt.dev domain cutover is a separate
  owner step; the domain serves another repo's `dist/` today.
- **Root layout.** `web/` is self-contained with its own lockfile and CI-
  independent build, so Python tooling is unaffected. `readme_sync.py`
  needs a `COMPONENTS["web"]` entry and `web/tests`, or no row appears.
  Add Node and Vercel entries to `.gitignore`.

## Risks / Trade-offs

- Real exports leak a field → scrub test with allowlist, run in CI and
  before commit.
- Fixtures drift from real shapes → types mirror the store schemas; the
  later pipeline change owns validation.
- Chromium is a snap and may sandbox oddly → fall back to the apt
  `chromium-browser` path or `--no-sandbox` for the inspector only.
- Upgrade job gains a path by accident → the isolation test.
- `verify.sh` runs nothing in `web/` → capture `web/` test, `tsc`, build
  and Lighthouse output into `08-verify.md` by hand.
- Stale data → pages show data age; past 48 hours a stale label shows.
