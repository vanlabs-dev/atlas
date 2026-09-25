## Why

subnt.dev now builds its v2 Astro page from `data/*.json` (schema
`subnt/1.x`, file `schema/subnt-1.0.json` in the subnt repo). Atlas still
writes only the v1 root `index.html`, which the v2 build ignores. The live
page is frozen at hand-committed data (subnt `ad8368e`, 2026-09-23) while
the publisher reported success, so `atlas-subnt.timer` was stopped on the
Pi on 2026-09-24. Publishing stays off until Atlas writes the data files.

## What Changes

- Compose each edition as six data files, `edition.json`, `network.json`,
  `movers.json`, `mining.json`, `attention.json` and `code.json`, that
  validate against schema `subnt/1.0`. Atlas keeps ownership of every
  figure, lead, delta, stale decision and gap wording.
- Section builders return structured facts, notes, gaps, rows and series
  instead of `(kind, text)` sentence pairs.
- Run the operator-material scan on the serialised JSON, covering at least
  every token and pattern the subnt build bans, plus the em dash.
- Validate every file against a vendored copy of the schema before any
  write. A file that fails validation fails the pass closed.
- Add a schema test suite: composed files validate, empty editions
  validate, and the vendored schema matches the subnt copy when that
  checkout is present.
- Gate the publish on a fact digest over the six files with
  `composed_at`, `block` and `previous_composed_at` normalised out.
- **BREAKING**: remove the HTML renderer. The publish job no longer
  composes, scans or writes `index.html`. The inline SVG charts, CSS,
  relative-time script and HTML-only scan checks are deleted. The
  `page_file` config key is replaced by `data_dir`.
- Re-enable `atlas-subnt.timer` on the Pi once the export is deployed and
  one dry-run edition is checked.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `subnt-publish`: the edition contract changes from one HTML document to
  schema-valid data files. The as-of, delta, exclusion, chart, publish
  gate and disable requirements are restated for data files. The page
  contract requirement is removed. New requirements cover schema
  validation and the absence of any HTML output.

## Impact

- Code: `subnt/atlas_subnt.py` (builders, compose, scan, digest, publish,
  CLI; render path deleted), `subnt/config.json`.
- New file: `subnt/schema/subnt-1.0.json`, a byte copy of the subnt repo
  schema.
- Tests: `subnt/tests/test_subnt.py` rewritten from HTML parsing to JSON
  assertions; new schema tests. `fleet/tests/test_mining_agreement.py`
  calls `mining_facts` and must follow its new return shape.
- Dependency: `jsonschema` (Draft 2020-12). Present as a system package on
  the workstation (4.10.3) and the Pi (4.19.2). Nothing to install.
- Pi: state store `var/subnt/subnt.db` carries over; the first JSON
  edition compares against the last v1 publish. The timer is re-enabled
  as the final rollout step.
- subnt repo: Atlas writes only `data/`. The stale root `index.html` and
  the v1 pytest contract there are the subnt repo's cleanup, not this
  change's.
- Docs: `subnt/README.md`, `docs/decisions.md`.
