# Tasks

## 1. Payload and allowlist

- [x] 1.1 Add per-type field lists and project every fixture record in `web/src/data/*.ts`; drop `cueKind`, `confidence`, `gateState`, `netTaoMonth` from `types.ts`; verify `npm run typecheck` passes
- [x] 1.2 Update `scripts/allowlist.ts` (drop the four fields, add `blockRef`, `unratedReason`, `gpuMentionFiles`) and add the banned-source-field test; verify `npm --prefix web test` fails with a planted `net_tao_month` entry and passes without it
- [ ] 1.3 Add a build-output test that greps `.next` HTML and RSC files for `cueKind|netTaoMonth|confidence|gateState` and the cue values; verify it fails on the pre-change build and passes after `npm run build`

## 2. Export

- [ ] 2.1 Remove the seven-day age cut; read the latest mining pass, current scans, live board and network rows; verify by a rehearsal run (task 6.1)
- [x] 2.2 Add `--out <dir>` and refuse to write into `src/data/fixtures` when it is given; verify with a unit test on the path guard
- [x] 2.3 Daily bins through the metric's commit reader and bot patterns with `c7` window semantics, binning in `scripts/bins.ts`; verify TS tests for a 7.0-day commit and a bot commit, plus a Python cross-check against `compute_activity`
- [x] 2.4 Export `gpuMentionFiles`, `block_ref`, `unrated_reason`; signals limited to named classes and non-shadow tiers; verify with the allowlist and signals-filter tests
- [x] 2.5 Update `web/README.md` (aging, `--out`, bins); verify the documented command matches the script

## 3. Mining page

- [x] 3.1 Sort by rank, then cut with public reason, then the rest; headline names rank 1; verify with a sort test on a fixture where a cut row has the largest gross
- [ ] 3.2 Labels: "Model estimate, TAO/mo at spot", read block, note text, "No GPU code found" with mention count, no VRAM on `possible`, "Top earner (excluding the owner)", CUT/UNRATED maps with unnamed fallback; verify word-map tests and a render check of the built page

## 4. Fleet, home, network, upgrades

- [ ] 4.1 Unsigned "places apart" everywhere; no ahead/behind text; apart label only at 40+; verify a test on the label helper and grep of the built HTML for "ranks ahead"
- [ ] 4.2 Cold wording "No commits for 30 days or more in the tracked repository"; verify on the built page
- [ ] 4.3 `DataAge` server stale badge from build time; home data age; no "today" for the data day; verify freshness tests and the built home HTML
- [ ] 4.4 Plain names for chain parameters, bar mode, root rotation, price units; "the N newest" for capped lists; network chart title without "daily"; home counts agree; verify word-map tests and the built pages
- [ ] 4.5 Null and empty guards (percent, means, `rows[0]`, `vitals[0]`, `events[0]`); "$257" precision; verify a build with empty fixtures in a test harness
- [ ] 4.6 Remove `@base-ui/react`, `class-variance-authority`, `lucide-react`; `@types/node` ^22; verify `npm install`, typecheck, build

## 5. subnt publisher (retired, latent)

- [ ] 5.1 `why_phrase` without direction per the spec delta; verify updated `subnt/tests` cases (two gap sizes differ, +50 and -50 equal)
- [ ] 5.2 Mining lead and notes for model 3; verify a test asserting no "not counted" or "largest earnable pool" and no band or rent text
- [ ] 5.3 Update `subnt/README.md`; run `python3 tools/readme_sync.py`; verify `tools/tests` pass

## 6. Integration (operator approvals)

- [ ] 6.1 Rehearsal export to the session scratchpad with `--out` (approved 2026-11-04); verify scrub, allowlist and diff review
- [ ] 6.2 Regenerate committed fixtures (needs a yes); every Python suite and `npm --prefix web test` and the build-output test pass; commit
- [ ] 6.3 Push (needs a yes); check the deployed pages for the banned fields and labels
