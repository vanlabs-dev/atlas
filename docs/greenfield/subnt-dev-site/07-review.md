# subnt-dev-site: outside-voice review

Date: 2026-10-30. Session 3. Read from docs and artifacts only.
Status of each finding: open until the owner decides. Fold accepted ones
in with `/opsx:update`.

## Critical

1. **The owner glance view is public.** The site is public, so every
   fixture and later every snapshot is world-readable. The repo is public
   too (MIT, anonymous HTTPS), so fixtures also sit in git history for
   good. Fleet attention and mining triage describe the owner's own
   positions. Decision `subnt-publish` (docs/decisions.md ~l.657) already
   set the rule: "recorded, dated, operator-free figures". The proposal
   does not say whether it still holds.
   Fix: add a spec requirement that site data is operator-free, and say
   which fleet and mining fields are public.
2. **Scrub by denylist is the wrong control.** Task 3.3 scans an export
   for token, IP, host and SS58 patterns. A new field, a subnet name, or a
   hotkey in free text passes. Fix: the export script builds each record
   from a named allowlist of fields, so unknown fields cannot flow. Keep
   the pattern scan as a second check. Define "private party" in the
   fixture-hygiene requirement (own addresses count).
3. **Task 3.2 is under-specified.** It does not name the stores, the path,
   or how a LAN-only Pi is read from the workstation. Fix: list the
   stores and the read method in the task, and state that the export is
   read-only. Fresh live data in a public repo also leaks current state;
   consider a stale snapshot or rounded values.

## Major

4. **Domain collision.** Open question 6 (retire subnt-trader timing) is
   unresolved in the brainstorm and never closed in the proposal.
   subnt.dev is served today from another repo's `dist/`. Task 6.3 points
   the domain at Vercel and may take that page down. Fix: decide the
   cutover order, or deploy to a Vercel preview URL and move the domain
   as a separate owner step.
5. **`ignoreCommand` is fragile.** A bare `git diff HEAD^ HEAD` checks the
   last commit only. A multi-commit push with `web/` in an earlier commit
   is skipped. Fix: use `VERCEL_GIT_PREVIOUS_SHA` with a fallback to
   build, and test both cases in 1.2.
6. **`verify.sh` does not cover `web/`.** It runs `npm test` only at the
   repo root, and the root has no `package.json`. Web tests, `tsc`, the
   build, and Lighthouse would never be run by the gate. Fix: add a task
   to capture `web/` command output into `08-verify.md` by hand, and add
   a `test` script to `web/package.json` that runs the scrub test.
7. **Weak acceptance criteria.** "Excellent UX", "distinct", "first
   screen states what Atlas is", and Lighthouse "no failures" cannot
   fail. Fix: set Lighthouse accessibility >= 95 per page, add a
   contrast check (WCAG AA), and name the home first-screen content (one
   sentence plus four links visible at 1280x720 and 390x844).
8. **Stale data has no rule.** The spec shows a data age but never says
   what happens when it is old. Fix: add a threshold and a stale label.
   This matters most once real data lands.

## Minor

9. **README sync wiring.** `tools/readme_sync.py` counts a directory as a
   component only if it has `tests/` or `systemd/`. Task 1.3 must add a
   `COMPONENTS["web"]` entry and a `web/tests` directory, or no row
   appears. Note the `subnt-publish` retired row (README l.130): reword
   it with 6.2.
10. **`.gitignore` lacks `node_modules/`, `.next/`, `web/.env*`, `.vercel/`
    and `*.tsbuildinfo`.** Add them in 1.1. The Pi pulls `main`, so keep
    `web/` free of anything large.
11. **Chromium path.** Design says `/usr/bin/chromium-browser`. That is a
    shim for the snap at `/snap/bin/chromium`, which exists. Use the snap
    path directly. The brainstorm note "not found" is out of date.
12. **Order.** Tasks 3 (data) run before 4.1 (design direction). Types
    may need to change after the design. Accept: types are cheap to edit.
    Alternative: build the home page before the export script.
13. **Next.js 16.** Verified: `latest` is 16.4.3. The choice is sound.
14. **Isolation test is sound.** `ALLOWED` is an allowlist, so `web/` is
    rejected already. The test guards against a future edit to `ALLOWED`.
    Keep as planned.

## Verdict

Resolved 2026-10-30. The owner chose operator-free data (option A).
Findings 1 to 11 were folded into the proposal, spec, design and tasks
with `/opsx:update`. Findings 12 to 14 needed no change.
