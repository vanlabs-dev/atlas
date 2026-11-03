# Proposal

## Why

subnt.dev overstates what Atlas knows. It calls a scan result "Runs on a
CPU", presents an unlabelled earnings model as what a slot earns, sorts
by that figure over Atlas's own rank, ships the dropped accumulate/fade
cue in its payload, and says "today" about data that is days old. The
WP4 mining model and the WP8 signal changes also left the fixture export
able to leak rent (`net_tao_month`, `above-budget-band`) and to publish a
pre-WP4 model, because it reads data seven days old. Audit items E1 to
E10 (2026-11-02).

## What Changes

- Fixture export reads the latest stored mining pass, feasibility scan,
  fleet board and network rows. The seven-day age cut is removed;
  rounding to four significant digits stays (operator decision 1A,
  2026-11-04). An `--out` flag writes a rehearsal anywhere but the
  committed fixture directory.
- Export daily commit bins use the activity metric's own reader: bot and
  CI authors are left out and the window edge matches `c7`/`c30`.
- Allowlist: drop `cueKind`, `confidence`, `gateState`, `netTaoMonth`.
  Add `blockRef`, `unratedReason`, `gpuMentionFiles`. Never list
  `payback_days`, `required_band`, `band_assumed`, `cut_detail`,
  `rent_*`. Signals export only named, non-shadow classes.
- Data modules project each fixture to its typed fields, so a field
  removed from the type leaves the served payload even before fixtures
  are regenerated.
- Mining page: sort by stored Atlas rank, then cut subnets with a public
  reason, then the rest. The gross column is labelled as a model estimate
  at spot with its block. `possible` renders "No GPU code found", plus the
  GPU-mention file count. No "0 GB VRAM" beside it. "Top earner" says it
  excludes the owner. `above-budget-band` renders "Needs a larger GPU".
  `prune-risk` gets a public reason.
- Fleet and home: no direction cue in words or sign. The gap renders as
  "N places apart". "Code and price apart" only at a gap of 40 or more.
  "Gone cold" becomes "No commits for 30 days or more in the tracked
  repository".
- Data age: the stale label is in the server-rendered HTML when the data
  is already past 48 hours at build. The home page shows its data age.
  No "today" for a data day that is not today.
- Plain-English names for chain parameters, gate bar mode, root rotation
  and price units. Event lists say "the N newest" instead of a total
  that is really a query limit. The network chart stops calling sparse
  readings daily. Home counts agree.
- Null and empty guards on every board.
- Retired subnt publisher (latent, not re-enabled): `why_phrase` states no
  direction; mining notes match model 3 (no "hardware not counted", no
  "largest earnable pool").
- Remove unused web dependencies; `@types/node` matches Node 22.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `subnt-dev-site`: payload limited to typed fields; data age and stale
  label in server HTML; mining view follows the stored ranking and its
  labels; no direction cue; honest event-count and label wording; export
  reads the latest stored pass and matches board activity counts.
- `subnt-publish`: attention reasons state no direction; mining notes
  describe model 3.

## Impact

- `web/scripts/export-fixtures.ts`, `web/scripts/allowlist.ts`,
  `web/src/data/*`, `web/src/lib/*`, board pages and components, home
  page, `web/tests/`, `web/package.json`, `web/README.md`.
- `subnt/atlas_subnt.py`, `subnt/tests/test_subnt.py`, `subnt/README.md`.
- No Pi change. The export reads Pi stores read-only over ssh. Each
  regenerated fixture is a public publish through Vercel and needs the
  operator's yes before commit and before push.
- Out of scope: multi-repo activity per subnet (proposed separately as
  `fleet-multi-repo-activity`); the WP8 signal ledger; the WP4 model.
