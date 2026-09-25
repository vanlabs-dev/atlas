## 1. Schema and config

- [x] 1.1 Copy `~/src/github/vanlabs-dev/subnt/schema/subnt-1.0.json` byte for byte to `subnt/schema/subnt-1.0.json`
- [x] 1.2 In `subnt/config.json`, replace `page_file` with `data_dir: "data"` and update `_comment`
- [x] 1.3 Add a schema loader that builds a `jsonschema.Draft202012Validator` from the vendored copy and raises `SubntError` with a named reason when the file or the library is missing

## 2. Builders return schema blocks

- [x] 2.1 Rewrite `network_facts` to return the `vitals` block: facts `bar` (observed from `gate_state.observed_at`, not the edition block), `tao`, `staked`, `accounts`, `spec`, with deltas as `{text, direction}` or null; release and rule changes as notes; stale bar and missing inputs as gaps; plus the section lead
- [x] 2.2 Rewrite `mover_facts` to return the `lead` and `board` blocks: lead mover fact, sortable rows with `figure`, `sort` and a detail fact per mover, risk, contested and hover lists as notes; lead text
- [x] 2.3 Rewrite `mining_facts` to return the `board` block: facts `ranked` and `head`, top-ten rows, entered/left/unchanged as notes, unrated as a gap; lead text
- [x] 2.4 Build the `attention` section from `attention_rows` and `group_attention` as one `groups` block; a missing name is a null `name` plus a named gap; no-rows case is a gap; lead text
- [x] 2.5 Rewrite `code_facts` and `narrative_facts` into the `code` and `narrative` blocks of `code-narrative`: fact `pushed` from the stored seven-day measure, verdicts, re-points and adoptions as notes; lead text
- [x] 2.6 Turn the stored series into schema `series` (`bar-trend`, `tao-trend`, `share-strip` with `log` and `mark`, `lead-mover-trend`), each with a caption stating its figures, emitted only with two or more points
- [x] 2.7 Give every section an empty-store path that still returns a non-empty lead and a named gap

## 3. Compose, scan, validate

- [x] 3.1 Change `compose` to return the six documents (`edition` plus five sections) sharing one `composed_at` (UTC, to the second, `Z`) and one `block`; `edition.json` carries `first_edition`, `previous_composed_at` from stored `published_at`, and `headline` from `_lede`
- [x] 3.2 Serialise each document with `ensure_ascii=False`, `indent=1` and a trailing newline
- [x] 3.3 Rewrite `scan` to run over each serialised file, prefix hits with the file name, add the subnt `leak.mjs` tokens and patterns Atlas lacks and the em dash, and drop the browser-fetch, external-asset and stylesheet checks
- [x] 3.4 Make `build` compose, serialise, scan and validate, returning every scan hit and schema error with file and path; it writes nothing

## 4. Publish

- [x] 4.1 Rewrite `fact_digest` over the six files with `composed_at`, `block` and `previous_composed_at` removed, canonical sorted-key JSON in file-name order
- [x] 4.2 Read the committed side with `git show HEAD:data/<name>.json`; treat a missing file as a change
- [x] 4.3 Write the six files atomically into `<checkout>/<data_dir>/`, stage them by explicit path, commit `Publish edition` under the configured identity, push; keep the dirty check, ff-only sync, git environment and no-reset behaviour
- [x] 4.4 Update `run` so `publish: false` reports the intended data directory, and so figures, `published_at` and the digest persist only after a changed publish

## 5. Remove the HTML renderer

- [x] 5.1 Delete `render`, `_CSS`, `_FONTS`, `_ICON`, `_esc`, `_facts_list`, `_kpi`, `_section`, `_hero`, `_attention_body`, `_movers_body`, `_AGO_JS`, `sparkline`, `_points`, `distribution_svg`, `meter`, `_ASOF_RE`, `_AGO_RE`, and the `(kind, text)` helpers once unused
- [x] 5.2 Update the CLI: `compose` prints the six files as one JSON object on stdout and the summary on stderr, `--out DIR` writes the six files into `DIR`, exit 2 on any scan hit or schema error
- [x] 5.3 Confirm with `grep -n "html\|<svg\|index.html" subnt/atlas_subnt.py` that no HTML path remains

## 6. Tests

- [x] 6.1 Rewrite `subnt/tests/test_subnt.py` from HTML parsing to JSON assertions, keeping every existing behaviour test (read-only, stale bounds, deltas, attention, code, exclusion, publish, grouping, series) against the new shape; delete the readability, relative-time, scripting-off and SVG tests
- [x] 6.2 Add schema tests: a full edition and an all-stores-absent edition each validate, all six files share `composed_at` and `block`, and a doctored file (empty `lead`, em dash, wrong `schema`) fails `build` with the file named
- [x] 6.3 Add the drift test: compare the vendored schema to `$SUBNT_CHECKOUT`, else `~/src/github/vanlabs-dev/subnt`, else the configured `checkout_dir`; skip when none exists
- [x] 6.4 Add the scan-parity test: each subnt `leak.mjs` token and a sample for each pattern, held as literals, is reported by `scan`
- [x] 6.5 Add digest tests: same facts at a later compose time and a later panel block leave the gate closed; a moved fact opens it; a missing committed file opens it
- [x] 6.6 Add publish tests on a local temporary repo: the commit touches only the six data files, and a pre-existing root `index.html` is untouched
- [x] 6.7 Update `fleet/tests/test_mining_agreement.py` to the new `mining_facts` return shape
- [x] 6.8 Run `python3 -m unittest discover -s subnt/tests -t subnt/tests` and the fleet suite; both green

## 7. End-to-end check against the subnt build

- [x] 7.1 Compose a fixture edition with `--out` into a scratch directory, copy the subnt checkout to scratch, replace its `data/*.json`, and run `npm ci && npm run build`; the build passes Ajv and the leak check

## 8. Docs

- [x] 8.1 Rewrite `subnt/README.md` for the data-file edition: files and blocks, digest gate fields, scan list, schema copy and drift test, commands, config
- [x] 8.2 Add a `docs/decisions.md` entry: JSON export shipped, renderer removed ahead of the subnt-v2 one-week plan, rollback by revert
- [x] 8.3 Update the `subnt-publish` row and the paused notes in `README.md`, preserving the operator's uncommitted edits in that file

## 9. Pi rollout (operator runs, Claude proposes the commands)

- [x] 9.1 After the operator pushes, `git pull` in `~/atlas` on the Pi and run the subnt test suite there
- [x] 9.2 On the Pi, compose from the real stores with `--out /tmp/subnt-data`, build a copy of `~/subnt` at `/tmp/subnt-check` against it, and confirm `npm run build` passes
- [x] 9.3 Run `python3 subnt/atlas_subnt.py publish` once by hand; confirm the Cloudflare build and that https://subnt.dev shows the new `composed_at`
- [x] 9.4 `systemctl --user enable --now atlas-subnt.timer` and confirm the next scheduled run
- [x] 9.5 Update the `subnt-timer-stopped` memory and the README paused notes to record the restart
