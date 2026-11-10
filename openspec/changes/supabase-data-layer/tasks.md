# Tasks

## 1. Shared contract and composer

- [x] 1.1 Move the field allowlist from `web/scripts/allowlist.ts` to `sitedata/allowlist.json`, and the scrub patterns from `web/scripts/scrub.ts` to `sitedata/scrub.json`. Make both TS modules load the JSON. Verify that `npm test` in `web/` passes unchanged (banned fields, `FIELDS` parity, planted leaks).
- [x] 1.2 Move the Python program from `web/scripts/export-remote.ts` into `sitedata/compose.py`, returning the same raw rows. Port the export test's ban on age cutoffs (`cutoff|AGE_DAYS|<= ?`) to `sitedata/tests/test_compose.py`, and verify the test passes.
- [x] 1.3 Add `pick`, 4-significant-digit rounding, `binDaily` and the board assembly from `export-fixtures.ts` to `sitedata/atlas_sitedata.py` (`compose` command, prints the four boards as JSON). Verify it with a golden test: a fixed raw-row input gives boards identical in value and number type in Python and in the TS path.
- [x] 1.4 Add the scrub to `atlas_sitedata.py`, applied per board. Verify with unit tests that each planted leak from `web/tests/fixtures.test.ts` blocks its board, and that clean boards still pass.
- [x] 1.5 Add `sitedata/README.md` covering commands, inputs, the allowlist rule and the tests. Run `python3 -m unittest discover -s sitedata/tests` and verify it passes.

## 2. Fixture refresh through the composer

- [x] 2.1 Change `web/scripts/export-fixtures.ts` to run `python3 sitedata/atlas_sitedata.py compose` on the Pi over ssh and write its output, keeping the `--out` refusal rule. Delete `export-remote.ts` and `bins.ts`, or reduce them to what the tests still need. Verify that a `--out` rehearsal writes four boards and `npm test` passes.
- [x] 2.2 Update `web/README.md`: fixtures are now the fallback, and the composer is the single source. Verify that the documented rehearsal command runs as written.

## 3. Supabase store and Pi publisher

- [x] 3.1 Check Supabase's current free-plan pause rule and record the answer in `design.md` Open Questions. Then, with operator approval, create the Supabase project.
- [x] 3.2 Write `sitedata/supabase/001_boards.sql` (the `boards` table, row-level security on, an anon `SELECT` policy, no write policies) and apply it. Verify that an insert with the publishable key is rejected and a select succeeds.
- [x] 3.3 Add the `publish` command: read hashes in one GET, upsert only changed boards, exit non-zero on any upload error or missing `SUPABASE_URL` or `SUPABASE_SECRET_KEY`, and redact the key from all output. Verify with unit tests against a stub HTTP server: changed-only upload, store down leaves rows unchanged, missing key exits before composing, key absent from error text.
- [x] 3.4 Add `sitedata/systemd/atlas-sitedata.{service,timer}` (`OnCalendar=*:25`, `Persistent=true`, `OnFailure=atlas-notify-failure@%n.service`). Verify with `systemd-analyze verify` on both files.
- [ ] 3.5 With operator approval: add the secret key to `~/.hermes/.env` on the Pi, pull `main`, and run `atlas_sitedata.py publish` once by hand. Verify that the four rows exist in Supabase with the expected generated times.

## 4. Site data layer

- [x] 4.1 Add a server-only reader in `web/src/data/source.ts`: a `'use cache'` fetch of one board with `cacheLife({ revalidate: 900 })`, throwing on non-200 or empty. The outer function falls back to the committed fixture, and without `SUPABASE_URL` it uses the fixture directly. Verify with unit tests for the fixture path, the configured path (stub fetch) and the error path.
- [x] 4.2 Switch `mining.ts`, `fleet.ts`, `network.ts` and `upgrades.ts` to the reader, keeping their signatures and the `FIELDS` projection. Verify that `npm run typecheck` passes, that `npm run test:build` passes with no Supabase settings, and that the served payload test still finds no undeclared field.
- [x] 4.3 Replace `SITE_BUILT_AT` and `staleAtBuild` with a read-time stale label in `data-age.tsx` and `freshness.ts`. Verify with `tests/freshness.test.ts`: a board older than 48 h at read time renders the stale label in server HTML.
- [ ] 4.4 Set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` in a Vercel Preview deployment. Verify that pages show the Supabase boards. Then point the reader at a bad URL in the Preview and verify that the page keeps the last good data, not an error or a blank. If Next does not keep the stale entry, apply the sentinel fallback from `design.md` and re-check.
- [x] 4.5 Update `web/README.md` (Data and Deploy sections) for the live source, the environment variables and the fallback. Verify that the README states no fixture-push workflow for data.

## 5. Upgrades board before go-live

- [x] 5.1 Fix the unreleased-changes case: when the pending range's spec is not above the live spec, the board must not say "spec N is merged and waiting" and the heat map must not repeat the live spec's row. Label it as changes merged since spec N. Verify with a `words.test.ts` case built from the 2026-11-10 data (live 488, pending range at 488 with one CI commit).

## 6. Go-live

- [ ] 6.1 Set the Vercel Production environment variables, deploy `main`, then install and enable `atlas-sitedata.timer` on the Pi (operator approval). Verify that after the next `:25` run the home page shows the latest mining pass time, and Network shows the latest probe pass, with no new deploy.
- [ ] 6.2 Verify the failure path end to end: stop the timer's network access for one run (or use a bad URL), check that the Telegram job-failure alert fires, and check that the site still serves the last boards.
