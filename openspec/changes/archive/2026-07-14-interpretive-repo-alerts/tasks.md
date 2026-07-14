## 1. Area and pallet map

- [x] 1.1 Add default `AREA_MAP` (top-level dir → class `core`/`node`/`noise` + label) and `PALLET_MAP` (`pallets/<name>` → domain label) constants in `telegram/atlas_telegram.py`, seeded from the design's defaults; noise is allowlist-only
- [x] 1.2 Add an area classifier that returns `unknown` (its own class, not noise) for any top-level dir absent from `AREA_MAP`, and groups repo-root files (no `/` in path) under a synthetic `(root)` noise area
- [x] 1.3 Load optional `repository_update.area_map` / `pallet_map` overrides from config, falling back to the code defaults
- [x] 1.4 Document the new optional config keys in `telegram/config.json` `_comment` and `telegram/README.md`

## 2. Area aggregation and line churn

- [x] 2.1 Add a helper that aggregates the recorded `files` into per-area `{class, label, file_count, additions, deletions}`, treating `None` additions/deletions as 0 for sums but still counting the file
- [x] 2.2 Add a compact number formatter (e.g. `3162 → 3.2k`) for line-churn rendering
- [x] 2.3 Propagate `files_truncated` into the aggregation so core/unknown areas render a `≥` lower-bound marker
- [x] 2.4 Add a helper that extracts touched pallet domains from `pallets/<name>/...` paths via `PALLET_MAP`, de-duplicated and order-stable

## 3. Verdict

- [x] 3.1 Implement `_repo_verdict(rng, live, areas, policy)` as the ordered decision table from design decision 3: (1) incomplete/non-fast-forward → low-confidence; (2) spec bump; (3) unknown area; (4) light touch only when core line-churn > 0 and its share of total line churn < ratio (default 0.15); (5) core change with pallet domains; (6) node/network; (7) neutral fallback
- [x] 3.2 Compute the light-touch share from line churn (adds+dels), falling back to file-count share only when total churn is zero/None
- [x] 3.3 Make the verdict the headline reason string in `_build_repo_event` (headline survives render truncation); echo any low-confidence caveat once in the body

## 4. Commit filtering

- [x] 4.1 Implement a commit filter/ranker over subjects only: drop `^Merge ` and `ci|test|docs|build|style` prefixes, and `chore` unless the subject names a release (`spec_version`/`version`/`release`); rank `feat|fix|refactor|perf` and protocol-keyword subjects first; return up to five
- [x] 4.2 When the ranked list is empty, emit one honest line stating no feature or fix commits in range (dominated by tooling); optionally suffix a kept commit with a PR number parsed from a related merge subject
- [x] 4.3 Frame the commit list as "substantive subjects," never as the commits that touched a specific area (no commit→file map is recorded)

## 5. Rewrite the breakdown

- [x] 5.1 Rewrite `_breakdown_lines` to emit, in priority order: spec/both-clocks summary, `Protocol changed` line (core areas: file count + `+adds/−dels`), `New / unclassified area` line when any unknown-class dir changed, `Housekeeping` line (noise/node areas, counts only), pallet-domain line when applicable, filtered commits, and the unchanged `from recorded change data · effects not verified` trailer
- [x] 5.2 Route all dynamic text through the existing `render_html` params (headline/lines/expandable/trailer) so `html_escape` and the shrink loop apply; keep commits last inside the expandable so end-truncation sheds them first. Do NOT write bespoke truncation or escaping
- [x] 5.3 Confirm no em dashes are emitted (rely on the existing `_typography` normalizer; add a targeted assertion) and that all lines remain single-fact `·`-separated

## 6. Tests

- [x] 6.1 Fixture + test: noise-dominated large range → verdict says light protocol touch, protocol line shows core areas with churn, housekeeping line lists noise dirs separately
- [x] 6.2 Fixture + test: real `spec_version` bump → verdict leads with the spec bump and live delta, even when file counts are dominated by tests/CI
- [x] 6.3 Fixture + test: mixed commits → merge/ci/test filtered out, feat/fix shown, a release `chore: bump spec_version` retained; and a no-meaningful-commits range emits the honest line
- [x] 6.4 Fixture + test: pallet touch → pallet name and governed domain surfaced from `PALLET_MAP`
- [x] 6.5 Fixture + test: unknown top-level dir → surfaced on its own line and drives the verdict, NOT folded into housekeeping
- [x] 6.6 Fixture + test: `files_truncated` range → areas render `≥` lower-bound markers and the verdict is low-confidence
- [x] 6.7 Fixture + test: repo-root file (e.g. `snapshot.json`) with large churn → grouped under `(root)` housekeeping, does not appear as a protocol area; and line-churn ratio (not file count) decides a high-churn/low-file-count pallet change as core, not light
- [x] 6.8 Test: rendered body stays within `message_max_chars` and contains no em dashes for the largest fixture
- [x] 6.9 Run the full `telegram` test suite off-device and confirm green

## 7. Close-out

- [x] 7.1 Update `telegram/README.md` and any operator-setup docs describing the alert body format
- [x] 7.2 On-device acceptance on the Pi (2026-07-14): `git pull` fast-forwarded to 9b6861c, 51 tests green via `python3 -m unittest`, and a read-only dry render against the live `repotrack.db` confirmed the interpreted body (verdict, signal/noise split, both-clocks Δ+6, filtered commits) renders correctly with real data
