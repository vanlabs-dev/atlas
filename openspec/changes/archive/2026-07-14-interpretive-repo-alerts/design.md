## Context

The outbound notifier builds repository-update alert bodies in
`telegram/atlas_telegram.py`:

- `_breakdown_lines(rng)` — emits `top areas: ...` (raw file counts across all
  dirs), `tags: ...`, the first five commit subjects, and the
  `from recorded change data · effects not verified` trailer.
- `_build_repo_event(rng, live, pending, max_chars)` — picks the headline
  reason (spec bump / review needed / protocol-area change) and assembles the
  header lines, `_both_clocks_line`, and the breakdown.
- `_dominant_area` / `_digest_line` — churn-digest helpers.

The recorded change range (`rng`) already carries everything needed:
`files` as `{path, additions, deletions}` (up to 2000), `commits` as
`{sha, subject}` (up to 500), `tags`, `prev_spec`, `new_spec`, and the
truncation / non-fast-forward flags. The notifier config already declares
`protocol_dirs` (`pallets, runtime, precompiles, common`) and `churn_dirs`
(`.github, docs, website, vendor, sdk`).

The gap is purely presentational: the classifier knows signal from noise, but
the display does not use that knowledge, discards line churn, and shows the
wrong commits. Grounding the area vocabulary in the live
[opentensor/subtensor](https://github.com/opentensor/subtensor) tree confirms
a stable mapping of top-level dirs and pallet names to meaning.

## Goals / Non-Goals

**Goals:**
- Every significant repo alert leads with a plain-language verdict.
- The area breakdown separates core-protocol change from housekeeping and
  quantifies protocol change by line churn, not just file count.
- The commit list shows meaningful commits, or says there are none.
- `pallets/` touches name the pallets and what they govern.
- Zero new capture, zero re-fetch, zero network calls; body stays within
  `message_max_chars`; no em dashes; structured single-fact lines.

**Non-Goals:**
- No change to the repository tracker's capture, schema, or classification
  (deny-by-default churn tiering is unchanged).
- No GitHub API / PR-title resolution — branch names and recorded subjects are
  the only commit signal used.
- No fix to `spec_version` reading in the tracker; the "repo spec unknown"
  case is only surfaced more clearly in the presentation.
- No change to the `chain-runtime-upgrade`, `schema-drift`, or
  `knowledge-ingestion` classes.

## Decisions

### 1. A single config-driven area map with FOUR display classes

Introduce one lookup that classifies each top-level directory into a class
(`core`, `node`, `noise`, `unknown`) with a human label, plus a pallet map
keyed by the `pallets/<name>` segment giving a domain label. Defaults live in
code (so the feature works with today's `config.json`) and are overridable via
`repository_update.area_map` / `repository_update.pallet_map`.

Default area map (from the live subtensor tree):
- **core**: `pallets`, `runtime`, `precompiles`, `common`, `primitives`
- **node**: `node`, `chainspecs`, `chain-extensions`
- **noise** (explicitly enumerated): `vendor`, `website`, `docs`, `sdk`,
  `.github`, `ts-tests`, `eco-tests`, `clones`, `scripts`, `.maintain`,
  `support`, `ink-contract`, `.agents`, `.claude`, `.vscode`, and the synthetic
  `(root)` bucket (see decision 2)
- **unknown**: any top-level dir NOT in the three lists above

The `unknown` class is the critical correction. The classifier escalates a
range to significant precisely when it contains a top-level dir never seen
before; folding unknown dirs into `noise` at display time would hide the very
thing that fired the alert. Unknown dirs therefore render on their own line
("New / unclassified area") and feed the verdict, mirroring the classifier's
deny-by-default posture in the presentation layer. Noise is
allowlist-only — nothing reaches the noise bucket unless it is explicitly
named.

Default pallet map: `subtensor` → staking / emissions / weights;
`admin-utils` → governance params; `swap`, `limit-orders`, `alpha-assets`,
`transaction-fee` → dTAO economics; `drand` → randomness; `shield` → MEV
shield; `commitments` → commit-reveal; `crowdloan` → crowdloan; `proxy`,
`utility` → account tooling.

Rationale: keeping the existing `protocol_dirs` / `churn_dirs` for
classification untouched avoids re-testing the tiering logic; the richer map is
display-only.

Alternative considered: reuse `protocol_dirs`/`churn_dirs` directly for display.
Rejected because they are two coarse buckets with no labels, no `node` middle
tier, and — fatally — no way to distinguish an unknown dir from noise.

### 2. Line churn summed per area, truncation made explicit

Aggregate `additions`/`deletions` per top-level dir alongside the file count.
`None` values (binary files / unparsable numstat) are treated as 0 for the sum
but still counted as changed files. Files with no `/` in their path (repo-root
files such as `Cargo.lock`, `Cargo.toml`, `snapshot.json`) are grouped under a
synthetic `(root)` area classed as noise, so a large generated root file cannot
masquerade as a protocol area. Core and unknown areas render
`pallets 87 files +3.2k/−1.1k`; noise/node render counts only to save space.
Large numbers use a compact `k` suffix.

When `files_truncated` is set the recorded file list is a prefix, so every
count and churn sum is a lower bound: such areas render with a `≥` prefix
(`pallets ≥87 files ≥+3.2k/−1.1k`) and the verdict is marked low-confidence
(decision 3). This is not an edge case — the classifier deliberately routes
truncated ranges to significant because churn cannot be proven, so the
breakdown must state its own incompleteness rather than imply authority.

### 3. Verdict derived deterministically, ordered so it never lies

The verdict is chosen from a decision table over recorded facts, so it is
testable and never invents meaning. Order matters — each rule assumes the
earlier ones did not fire:

1. **Incomplete record first.** If `non_fast_forward` is set, or
   `files_truncated` is set and no `spec_version` change is recorded →
   `large / incomplete range · review` (low-confidence). A truncated file list
   makes any signal/noise ratio unreliable, so we do not pretend to judge it.
2. **Spec bump.** Else if `prev_spec` and `new_spec` are both known and differ →
   `RUNTIME SPEC BUMP <a> → <b>`, with the live delta appended. This outranks
   the ratio because a runtime release is the strongest signal even when file
   counts are dominated by tests/CI.
3. **Unknown area.** Else if any `unknown`-class dir changed → `NEW / unmapped
   area: <dirs>` (surface, never bury). This is what the classifier escalated
   for.
4. **Light touch.** Else if `core` line-churn is greater than zero AND its share
   of total line churn is below a configurable ratio (default 0.15) →
   `large sync · LIGHT protocol touch`. Share is by **line churn**
   (`adds+dels`), not file count, and only applies when core churn actually
   exists — so this line never claims a protocol touch that did not happen.
   When total churn is zero/None across the range, fall back to file-count
   share.
5. **Core change.** Else if any `pallets/` domain touched →
   `core protocol change: <domains>`; else if other `core` dirs touched →
   `core protocol change: <areas>`.
6. **Node/network.** Else if only `node`-class dirs touched →
   `node / network change`.
7. **Fallback.** Else → `repository change` (neutral).

The verdict becomes the headline reason string (the `<b>` line), which
`render_html` never drops — only hard-truncates in the final fallback — so it
always survives. Confidence caveats from rules 1/truncation are appended to the
verdict and echoed once in the body, not repeated per line.

### 4. Commit filtering by subject convention (a heuristic, labelled as one)

There is no recorded commit→file mapping — `commits` is `{sha, subject}` and
`files` is range-aggregate — so commit selection ranks by **subject text
only**. The breakdown must not imply "these are the commits that changed
pallets"; it presents "the most substantive-looking subjects in the range."

Drop subjects matching `^Merge ` or a conventional-commit noise prefix
(`ci`, `test`, `docs`, `build`, `style`, and `chore` UNLESS the subject also
contains a release keyword `spec_version` / `version` / `release` — a
`chore: bump spec_version to 430` is the release signal, not noise). Rank the
rest: `feat`/`fix`/`refactor`/`perf` first, then subjects containing protocol
keywords (`pallet`, `runtime`, `spec_version`, `staking`, `emission`,
`weight`, `consensus`, `governance`), then the remainder. Show up to five. A
merge subject referencing a PR (`#1234`) may contribute the PR number as a
suffix on a kept commit but is not itself shown. If the ranked list is empty,
emit one honest line: no feature or fix commits in range (dominated by
tooling).

### 5. Reuse existing render infrastructure, do not rebuild it

Verified during scrutiny that three concerns are already solved and need no new
code — only correct use:
- **Escaping**: `render_html` `html_escape`s every dynamic value it is given.
  All new free-text (subjects, dir names, pallet labels) must flow through the
  `lines` / `expandable` / `trailer` parameters, never be pre-concatenated into
  markup — then it is safe (a subject like `Vec<PerU16>` is handled).
- **Size**: `render_html` already shrinks the expandable content in a loop, then
  drops the trailer, then trailing lines. So the body is assembled
  priority-ordered — verdict in the headline (never dropped), then spec, areas,
  then commits last inside the expandable so end-truncation sheds commits
  first — and no bespoke truncation is written.
- **Dedup**: delivery de-duplicates by `event_id` (`repository-update:range:N`),
  not body hash, so the richer body cannot re-page already-delivered ranges.
- **HTML failure**: the existing 400 → plain-text fallback is unchanged.

## Risks / Trade-offs

- [Verdict oversimplifies a nuanced range] → The verdict is backed by the
  explicit signal/noise split and spec line directly beneath it, so the
  operator can always see the numbers behind the one-liner; the verdict never
  hides data.
- [Area/pallet map drifts as the monorepo reorganises] → Map is config-driven,
  and a dir that falls out of the map lands in the `unknown` class, which
  surfaces prominently and marks the verdict — so drift makes alerts noisier
  (safe), never quieter (unsafe). Noise is allowlist-only for the same reason.
- [Subject-prefix filtering hides a meaningful commit with an unconventional
  subject] → The full commit count is still stated, ranking demotes rather than
  deletes, and the shown commits are explicitly framed as "substantive-looking
  subjects," not as the commits that touched a given area (no such mapping is
  recorded).
- [Line-churn inflated by `--no-renames`] → The tracker records diffs with
  `--no-renames`, so a file move counts as a delete plus an add in two areas
  and inflates churn. Documented as a known limitation of the magnitude signal;
  file counts and the verdict's ratio absorb it identically, and it does not
  change signal-vs-noise classification.
- [Truncated range presents lower-bound numbers] → `files_truncated` areas
  render with `≥` and the verdict drops to low-confidence, so partial data is
  never shown as authoritative.
- [Pretty presentation masks an upstream range-segmentation defect] → An
  abnormally large range (commits truncated at the 500 cap) most likely
  reflects a watermark gap or range-segmentation behaviour in the repository
  tracker, not a single real push. This change cannot fix that (it is
  presentation only) but mitigates it with the low-confidence verdict branch;
  the root cause is called out in Open Questions for a separate change.

## Migration Plan

Pure code + optional config change; no data migration. Deploy by `git pull` on
the Pi; the next hourly notifier scan renders the new bodies. Rollback is a
revert — no persisted state changes. Existing `config.json` works unchanged
(defaults in code); an operator may later add `area_map` / `pallet_map` to
override.

## Open Questions

- None blocking this change. The light-touch ratio threshold (default 0.15,
  applied to line churn) and the compact number format are tunable in review.
- Out of scope, flagged for a separate change: the 500-commit / 1736-file range
  that prompted this work is truncated at `MAX_COMMITS_RECORDED` and is likely a
  symptom of range segmentation / a watermark gap in `repotrack`, not a normal
  event. Presentation cannot make a backfill-sized range meaningful; if these
  recur, the tracker's range boundaries (or a per-range commit cap that splits
  rather than truncates) should be investigated on their own.
