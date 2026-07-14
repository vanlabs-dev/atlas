## Why

The subtensor repository-update alerts report mechanical facts (SHA range,
file counts, the first few commit subjects) but never interpret them, so the
operator cannot tell at a glance whether an alert matters. The "top areas"
line is a raw file-count histogram across all directories, so noise the
notifier already classifies as churn (`vendor`, `website`, `sdk`, `docs`)
dominates the display while the one signal directory (`pallets`) is buried
last; the commit list shows the first commits in range order, which are
almost always merge/CI/test commits; and per-file line churn already recorded
by the tracker is discarded. Operator feedback (2026-07-14): "None of the
info really tells me anything."

## What Changes

- Add a one-line **verdict** to every significant repository alert that
  classifies the range in plain language (e.g. "large sync, LIGHT protocol
  touch", "RUNTIME SPEC BUMP 429 → 430", "core protocol change: staking /
  emissions"), derived from the signal-vs-noise ratio, the `spec_version`
  delta, and which protocol areas were touched.
- Replace the single raw "top areas" histogram with a **signal / noise
  split**: a "Protocol changed" line listing core-protocol directories with
  file counts and line churn, and a separate "Housekeeping" line listing
  noise directories with counts only. Housekeeping is allowlist-only — a
  top-level directory the map does not recognise is surfaced as a **new /
  unclassified area**, never hidden, mirroring the classifier's escalation of
  never-seen directories.
- Surface **line churn** (`+additions / −deletions`) per protocol area, summed
  from the `additions`/`deletions` already recorded per file — a truer
  magnitude signal than file counts.
- **Filter the commit list** to meaningful commits: drop merge commits and
  `ci` / `test` / `chore` / `docs` / `build` / `style`-prefixed subjects,
  prioritise `feat` / `fix` / `refactor` / `perf` and protocol-keyword
  subjects, and state honestly when a range contains no feature/fix commits.
- Add a **pallet-level semantic map** (config-driven) so a `pallets/` touch
  names the pallets involved and what they govern (e.g. `subtensor` →
  staking / emissions / weights, `admin-utils` → governance params,
  `swap` / `limit-orders` / `alpha-assets` → dTAO economics).

All of the above is a presentation-layer change built entirely from data the
repository tracker already records. No new data capture, no re-fetching, and
no GitHub or network calls are introduced; the read-only, fail-closed design
is preserved.

## Capabilities

### New Capabilities
<!-- none: this reshapes an existing capability's breakdown requirement -->

### Modified Capabilities
- `telegram-integration`: the "Significant repository alerts carry a concise
  breakdown" requirement is strengthened from listing recorded fields to
  interpreting them — a verdict line, a signal-vs-noise area split with line
  churn, a filtered meaningful-commit list, and pallet-level semantic labels,
  all from already-recorded fields and within the existing message-size and
  no-em-dash / structured-single-fact-line constraints.

## Impact

- Code: `telegram/atlas_telegram.py` — the breakdown builder
  (`_breakdown_lines`), the repo-event reason/verdict logic
  (`_build_repo_event`), and the digest builder. A new config-driven area /
  pallet map is added (default in code, overridable via
  `telegram/config.json` `repository_update`).
- Config: `telegram/config.json` gains an optional `area_map` / `pallet_map`
  under `repository_update`; existing keys are unchanged.
- Tests: `telegram/tests/test_notifier.py` gains fixtures for a
  noise-dominated large range, a real spec bump, and a range with no
  meaningful commits.
- No change to the repository tracker's schema or capture, to classification
  (deny-by-default churn tiering is unchanged), or to any other class.
