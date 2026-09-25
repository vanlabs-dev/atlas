## Context

`subnt/atlas_subnt.py` (1,644 lines) composes an edition in three
layers: fact builders that read the stores read-only and return
`(kind, text)` sentence pairs plus a `figures` dict, `compose()` that
assembles them with series and the lede, and `render()` that turns the
result into one HTML document with inline CSS and SVG. `scan()`,
`fact_digest()` and `publish()` then gate and push `index.html`.

The subnt repo is past cutover: `main` builds the Astro page from
`data/*.json` (`src/lib/load.mjs`), validates each file with Ajv against
`schema/subnt-1.0.json`, rejects unknown file names, mixed editions and
leaks (`src/lib/leak.mjs`). The hand-committed files at subnt `ad8368e`
are the reference shape for every section. See proposal.md for why.

## Goals / Non-Goals

**Goals:**

- Builders produce schema blocks directly, so no sentence is parsed back
  into a figure.
- Output from `compose` is byte-stable for unchanged facts, so the digest
  gate holds.
- Every failure (schema, leak, git) fails closed before the first write.

**Non-Goals:**

- Subscriber blocks. Every block is `public`.
- Any change in the subnt repo, including removing its stale root
  `index.html` and v1 pytest contract.
- Changing store reads, stale bounds, mover thresholds or attention
  scoring. The SQL stays as it is.
- A config switch back to HTML. Rollback is a git revert.

## Decisions

### Builders return blocks, not sentences

Each builder returns `(blocks, figures)` where a block is a dict in the
schema's `public_block` shape: `facts`, `notes`, `gaps`, and optionally
`rows`, `groups`, `series`, `title`. Sentences that are not a single
figure (the release subject, rule changes, dereg-risk lists, top-ten
entries) become `notes`. Headline figures become `fact` objects with
`id`, `label`, `text`, `value`, `unit`, `ref_block` or `observed`,
`freshness` and `delta`.

Mapping, following `ad8368e`:

| File | Block ids | Content |
|---|---|---|
| `network.json` | `vitals` | facts `bar`, `tao`, `staked`, `accounts`, `spec`; series `bar-trend`, `tao-trend`, `share-strip` |
| `movers.json` | `lead`, `board` | lead mover fact and `lead-mover-trend`; sortable rows per mover, risk and hover lists as notes |
| `mining.json` | `board` | facts `ranked`, `head`; top-ten rows; entered/left as notes |
| `attention.json` | `groups` | one group per shared reason |
| `code.json` | `code`, `narrative` | fact `pushed`; verdicts, re-points and adoptions as notes |

Alternative: keep sentence builders and add a mapping layer that reads
`figures`. Rejected: the display text, freshness and gaps already live in
the builders, and a second layer would duplicate every branch.

### Fact dates come from the fact's own row

The bar reads `gate_state` without a block, so the `bar` fact carries
`observed` from `gate_state.observed_at`, not the edition block. A fact
stamped with the edition block would change every hourly livedata poll
and the digest gate would never hold. Mover rows keep their own
`from`/`to` blocks in the detail text, as v1 did.

### Leads are composed in Atlas

Each section needs a non-empty `lead`. The builder that owns the section
writes it from its own facts (the `ad8368e` wording is the template);
when the section has no facts, the lead names the missing input. The
current `_lede()` becomes `edition.json` `headline`.

### Serialisation

`json.dumps(doc, ensure_ascii=False, indent=1)` plus a trailing newline,
keys in schema order. `ensure_ascii=False` keeps the text the scan reads
identical to the text the subnt build reads, so an em dash or a token is
not hidden behind a `\u` escape. Floats are written as stored; no
rounding is added.

### Validation with the vendored schema

`subnt/schema/subnt-1.0.json` is a byte copy of the subnt file. `build()`
validates each file with `jsonschema.Draft202012Validator` after the scan
and before anything is written. The system `python3-jsonschema` is on
both machines (4.10.3 workstation, 4.19.2 Pi); an import failure fails
closed with a named reason rather than skipping validation.

The drift test reads the subnt schema from `$SUBNT_CHECKOUT`, else
`~/src/github/vanlabs-dev/subnt`, else the configured `checkout_dir`, and
skips when none exists. Reading it in a test is not an edition input.

Alternative: validate only in tests. Rejected: a store row can carry an
empty string or an em dash that no fixture predicts, and the subnt build
would then fail on push with the site stuck on the last deploy.

### Scan

`scan(files)` runs over each serialised file and returns hits prefixed
with the file name. It keeps `OPERATOR_TOKENS` and `_LEAK_PATTERNS`, adds
any subnt `leak.mjs` token or pattern Atlas does not yet have (private
`10.`, `127.`, `172.16/12` ranges, private key block, 32-byte hex,
Telegram bot token, `^next: `), and adds the em dash. The browser-fetch,
external-asset and stylesheet checks go with the renderer. A test holds
the subnt list as literals and asserts each one is caught.

### Digest gate

`fact_digest(files)` loads each file, drops `composed_at`, `block` and
`previous_composed_at` at the top level, and hashes the canonical
`json.dumps(..., sort_keys=True)` of the six in file-name order. The
committed side is read with `git show HEAD:data/<name>.json`; a missing
file yields a changed digest. `publish()` writes all six atomically
(`.tmp` then `os.replace`), stages `data/` by explicit path, commits
`Publish edition`, and pushes. The ff-only sync, dirty check, identity
flags and git environment are unchanged.

`previous_composed_at` comes from the stored `published_at`, formatted to
`YYYY-MM-DDTHH:MM:SSZ`.

### Renderer removal

Delete `render`, `_CSS`, `_FONTS`, `_ICON`, `_esc`, `_facts_list`,
`_kpi`, `_section`, `_hero`, `_attention_body`, `_movers_body`,
`_AGO_JS`, `sparkline`, `_points`, `distribution_svg`, `meter`,
`_ASOF_RE`, `_AGO_RE`, and the HTML-only scan checks. Series readers
(`theta_series`, `vitals_series`, `share_distribution`, `netuid_series`)
stay and feed `series`.

### Config and CLI

`page_file` is replaced by `data_dir` (default `data`). `compose` prints
the six files as one JSON object keyed by file name on stdout and the
summary on stderr; `--out DIR` writes the six files into `DIR`. Exit 2 on
a scan hit or schema failure, as today.

## Risks / Trade-offs

- [The first JSON edition compares against the last v1 figure set, a
  few days old] → Deltas are correct against the last publish, which is
  what the spec asks. `previous_composed_at` states that time.
- [Schema drift between repos] → The drift test fails on the workstation,
  where both checkouts exist. On the Pi a drift fails validation or the
  subnt build, never a wrong page.
- [Structured facts change `mining_facts`' return shape] →
  `fleet/tests/test_mining_agreement.py` is updated in the same change.
- [Removing the renderer before the week the subnt-v2 plan allowed] →
  v1 is already unreachable: subnt.dev serves `dist/` only. Rollback is
  `git revert` of this change plus restarting the timer.
- [`jsonschema` 4.10 and 4.19 differ in edge behaviour] → The schema
  uses only core 2020-12 keywords (`oneOf`, `$ref`, `pattern`, `not`,
  `const`, `enum`). Tests run on both machines before the timer starts.

## Migration Plan

1. Implement and test on the workstation, including the drift test.
2. Push Atlas. On the Pi, `git pull` in `~/atlas` and run
   `python3 -m unittest discover -s subnt/tests -t subnt/tests`.
3. On the Pi, compose from the real stores into a scratch directory and
   build a throwaway copy of the subnt checkout against it, so Ajv and
   the leak check see real data before anything is pushed:
   `python3 subnt/atlas_subnt.py compose --out /tmp/subnt-data`, then
   copy `~/subnt` to `/tmp/subnt-check`, replace its `data/*.json`, and
   run `npm ci && npm run build` there.
4. Run one `publish` by hand, confirm the Cloudflare build and the page.
5. `systemctl --user enable --now atlas-subnt.timer`.

Rollback: `systemctl --user stop atlas-subnt.timer`, revert this change,
pull on the Pi. The subnt site keeps its last good deploy throughout.
