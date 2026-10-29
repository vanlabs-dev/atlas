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
- **Fixtures from a one-off export plus scrub.** A script under
  `web/scripts/` reads the Atlas stores, drops or hashes sensitive fields,
  and writes JSON. A test fails on token-shaped strings, SS58 addresses
  outside an allowlist, IPs, and hostnames. Alternative: hand-written,
  rejected by the owner for realism.
- **Visual direction decided at apply.** Run `draw.mjs`, record the chosen
  direction in `web/DESIGN.md`, build the home page first, then the others.
  Inspector uses `/usr/bin/chromium-browser`.
- **Isolation.** `upgrade/allowed_paths.py` is unchanged: `web/` is not in
  `ALLOWED`. Add a test in `upgrade/tests` asserting the gate rejects
  `web/` paths. `web/vercel.json` `ignoreCommand` builds only when the diff
  touches `web/`.
- **Root layout.** `web/` is self-contained with its own lockfile and CI-
  independent build, so Python tooling is unaffected. `readme_sync.py`
  gets a `web` row.

## Risks / Trade-offs

- Real exports leak a field → scrub test with allowlist, run in CI and
  before commit.
- Fixtures drift from real shapes → types mirror the store schemas; the
  later pipeline change owns validation.
- Chromium is a snap and may sandbox oddly → fall back to the apt
  `chromium-browser` path or `--no-sandbox` for the inspector only.
- Upgrade job gains a path by accident → the isolation test.
