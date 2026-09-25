# subnt: the public edition

OpenSpec changes `subnt-renderer` and `subnt-json-export`. Composes the
public [subnt.dev](https://subnt.dev) edition from rows already persisted
in the livedata and fleet stores, all opened read-only, as six data files,
and publishes them into the `data/` directory of a second checkout when a
fact in them has moved. The subnt repo builds the page from those files;
Atlas renders no HTML.

Composing makes no chain call, no provider call and no model call. Every
figure traces to a stored row and carries its reference block or its
observation date. An input that is missing, or past its own stale bound, is
named in the files instead of estimated.

The publish path is one direction only. **Atlas writes subnt's `data/`;
subnt is never read back.** No file in the checkout outside `data/` is
touched, and none of it is an input to an edition. The stale root
`index.html` from v1 is left alone.

## Why this is a second reader, not a wrapper

`telegram/atlas_briefing.py` reads the same stores, but its section
builders return `List[str]` formatted for Telegram, and `compose()` appends
`_atlas_section` (the provider quota, watermark staleness) and closes with
either the LAN board URL or `next: pick mining.budget_band`. Carrying those
lines over would publish the board address and the budget-band prompt to
the open internet, which is exactly what the subnt build bans by name.

So this module re-derives each section as schema blocks, with the same SQL
semantics, and shares the read primitives rather than the line builders.

## Shared read points

Change any of these and this module is a caller you must check.

| Shared from | Used for |
|---|---|
| `telegram/atlas_briefing.py` `_Sources` | opening the four stores read-only |
| `telegram/atlas_briefing.py` `_movers` | ranking price and demand-share movers |
| `telegram/atlas_briefing.py` `_table`, `_one`, `_delta_pct` | store probing and figure deltas |
| `telegram/atlas_briefing.py` `stored_mining`, `mining_top_delta` | the mining board and its top-ten change |
| `telegram/atlas_telegram.py` `_release_for_upgrade` | the release subject for a runtime spec |
| `telegram/atlas_telegram.py` `resolve`, `open_source_ro` | path resolution and read-only opens |
| `fleet/atlas_fleet_dashboard.py` `build_board` | attention scoring and ordering |
| `fleet/atlas_fleet.py` `load_config` | the fleet config `build_board` needs |

`build_thesis`, `build_badges`, the cue glyphs and the numeric score are
board chrome. `build_board` produces them; this module drops them.

## The data files

Schema `subnt/1.x`. The subnt repo owns `schema/subnt-1.0.json`; a byte
copy lives at `subnt/schema/subnt-1.0.json`. Every file is validated
against the copy before anything is written, and a test fails when the copy
drifts from a subnt checkout that is present.

| File | Section | Blocks | Reads |
|---|---|---|---|
| `edition.json` | none | none | compose time, `MAX(panel_snapshot.block_number)`, the previous publish, the headline |
| `network.json` | `network` | `vitals`: facts `bar`, `tao`, `staked`, `accounts`, `spec`, `side-changes`; series `bar-trend`, `tao-trend`, `share-strip` | `livedata` `meta.last_live_spec`, `chain_param_events`, `gate_state`, `gate_events`, `network_vitals`, `panel_snapshot.share` |
| `movers.json` | `movers` | `lead` (the largest mover and `lead-mover-trend`), `board` (sortable rows, risk and hover notes) | `livedata` `panel_snapshot`, `gate_sides.hovering` |
| `mining.json` | `mining` | `board`: facts `ranked`, `head`; top-ten rows | `fleet` `mine_econ` (never `rent_band`) |
| `attention.json` | `attention` | `groups`: one group per shared reason | `fleet` metrics report through `build_board`, names from `livedata` `panel_snapshot.name` |
| `code.json` | `code-narrative` | `code` (fact `pushed`, verdict and re-point notes), `narrative` (adoption and cluster notes) | `fleet` `metric_activity.c7`, `signal_econ_verdicts`, `epochs`, `signal_adoptions` (`kind = 'model-id'`), `signal_events` |

Every section file carries the `composed_at` and `block` of
`edition.json`; the subnt build rejects a mix. All six are written on every
edition, including one whose every input is missing: each section then has
a lead and gaps that name the missing input. Every section and block is
`public`; subscriber blocks are not emitted.

Atlas owns every display string: fact text, freshness, delta text, leads,
notes and gap wording. The page computes no figure.

Serialisation is `json.dumps(ensure_ascii=False, indent=1)` plus a newline,
so the scan reads exactly the bytes the subnt build reads. A stored em dash
(a verdict line, a subnet name) is rewritten to a comma before it reaches a
file: the schema refuses one, and a refusal would stop every publish.

## Facts are dated from their own row

The bar carries `observed` from `gate_state.observed_at`, the vitals their
`date`. No fact is stamped with the edition `block`: that moves every
hourly panel poll, and a fact carrying it would move the gate every pass.

## Series

Series are recorded points, oldest first, with a caption stating the
figures shown. A series with fewer than two points is not emitted.

| Series | Points |
|---|---|
| `bar-trend` | `gate_state.theta`, last 48 readings; only while the bar is inside its bound |
| `tao-trend` | `network_vitals.tao_usd`, last 30 days |
| `share-strip` | newest `panel_snapshot.share` per netuid, sorted, `log`, `mark` at the emission-gate rank |
| `lead-mover-trend` | the lead mover's recent readings of the column it moved on |

## Attention is grouped, and its reason is derived

`score_subnet` returns a category, and on the real fleet **93 of 106 public
rows carry the same one**. One phrase per category therefore produced ten
identical lines that told a reader nothing.

`why_phrase()` derives the phrase from the score's own components
(`div_signed`, `cold`, `econ_fresh`, `pulse_spike`), stating direction in
words. `group_attention()` then collapses rows that share a reason. Each
group label states the reason once with its count
(`priced ahead of its code activity: 8 subnets`). A row carries netuid,
recorded name (or null, with the gap named in the block) and the reason.

The contract bans the numeric score, direction-cue glyphs and the board
thesis sentence. It does not ban direction stated in words, and a test
asserts no derived phrase contains a digit or a glyph.

## Stale bounds are per input

- **Emission-gate bar**: 26 hours (`stale_hours`, the briefing default).
  Past it, the bar is a gap and neither its fact nor its series is emitted.
- **Network vitals**: shown with their observation date. A daily row is
  never called stale for age alone.
- **Panel movers**: the window since the previous subnt publish, or
  `window_hours` before compose when there is no previous publish.

## Editions and deltas

Deltas compare against the **previous subnt publish**, never against the
Telegram briefing watermark. The figure set, the publish time and the fact
digest live in this module's own store, `var/subnt/subnt.db`. They are
written only after a successful publish, so a composed but unpublished
edition does not consume the comparison point.

A comparable fact (`bar`, `tao`, `pushed`) always carries `delta`: an
object with `text` and `direction`, or null when it did not move. A change
that rounds to zero is null. A first edition sets `first_edition` true,
`previous_composed_at` null, and every delta null.

## The publish gate is on the facts

`fact_digest()` hashes the six files with `composed_at`, `block` and
`previous_composed_at` removed. Those move every pass, every hourly poll
and every publish; hashing them would commit new timestamps over unchanged
facts. The committed side is read with `git show HEAD:data/<file>`; a
missing or unreadable file counts as a change. Files left in place keep the
compose time of the edition that is published.

## Before any write

Every file is scanned and validated. A hit fails the pass closed and
writes nothing.

- **Scan**: `OPERATOR_TOKENS` opens with the exact strings the subnt build
  bans (`src/lib/leak.mjs`), then the wider off-page list. The patterns
  cover SS58 addresses, private IPv4 ranges, private key blocks, 32-byte hex
  secrets, Telegram bot tokens, a line opening with `next: `, and the em
  dash. The scan runs over the raw text and over each string value on its
  own line, so a line-anchored pattern still fires. A test holds the subnt
  list as literals and asserts each one is caught.
- **Schema**: `jsonschema.Draft202012Validator` over the vendored copy. A
  missing schema file or library fails closed rather than skipping.

The guarded case is a stored row that itself carries operator material,
for example a verdict line quoting a path or an address: the composer
cannot know that in advance, the scan can.

## Commands

```
python3 subnt/atlas_subnt.py compose --dry-run         # print, write nothing
python3 subnt/atlas_subnt.py compose --out /tmp/data   # also write the six files
python3 subnt/atlas_subnt.py publish                   # the full pass
```

`compose` prints the six documents as one JSON object on stdout and a
summary (problems, byte count, digest, window start, block) on stderr. It
exits 2 when the scan or the schema finds anything.

## Config

`subnt/config.json`. Rollback: `enabled: false` stops compose and publish
and touches nothing else; `publish: false` composes and reports the data
directory it would have written, but writes nothing.

| Key | Meaning |
|---|---|
| `enabled` | master switch for the pass |
| `publish` | write, commit and push; `false` composes only |
| `checkout_dir` | the subnt checkout |
| `data_dir` | the directory inside it the six files are written to |
| `state_db` | this module's own store, for deltas and the publish digest |
| `commit_name` / `commit_email` | passed per invocation with `git -c`; the device has no `~/.gitconfig` |
| `window_hours` | the mover window on a first edition |
| `stale_hours` | the emission-gate bar bound |
| `price_move_threshold_pct` / `share_move_threshold_pct` | mover thresholds |
| `attention_rows` | the attention cap |
| `live_db` / `fleet_db` / `repo_db` / `knowledge_db` | the stores, read-only |

## Failure modes

Every one of these fails the pass closed and leaves the checkout unchanged:
a missing checkout, a checkout that is not a repository, a dirty checkout,
a scan hit, a schema failure, a missing schema or validator, and a push
with no usable write credential. A failed push leaves the local commit in
place and the last Cloudflare deploy live; recovering it is the operator's
call, and this module does not reset.

Git can never prompt. Every call runs with `GIT_TERMINAL_PROMPT=0`,
`GIT_ASKPASS`, `ssh -o BatchMode=yes`, stdin closed and a 120s timeout, so
a missing credential fails the pass instead of hanging a timer-driven unit.

Identity is passed per invocation with `git -c user.name` and
`git -c user.email`. The device has no `~/.gitconfig`, so this is required:
without it the commit fails outright.

**It creates and moves no credential.** That stays an operator decision.

## On the device

The original publisher has been live since 2026-09-10. The subnt publisher
rename was deployed on 2026-09-22 with its prior publish state preserved.
Cloudflare serves https://subnt.dev from the subnt repo's Astro build of
`data/`; unknown paths return HTTP 404. `www` is not configured.

**Paused 2026-09-24 to 2026-09-26.** `atlas-subnt.timer` was stopped
while the deployed code wrote only the v1 `index.html`. The
`subnt-json-export` rollout resumed it on 2026-09-26: the first
data-file publishes are `d61476f` and `de72097` in the subnt repo, and
the state store carried over, so the first one compared against the last
v1 publish.

| | |
|---|---|
| Atlas checkout | `/home/pi/atlas`, remote `https://github.com/vanlabs-dev/atlas.git`, pulls anonymously |
| subnt checkout | `/home/pi/subnt`, remote `git@github.com:vanlabs-dev/subnt.git` |
| Publish credential | a write-scoped deploy key for the subnt repo alone, `~/.ssh/id_ed25519_subnt`, selected by a `Host github.com` entry with `IdentitiesOnly yes` |
| `~/.gitconfig` | does not exist, which is why identity is passed per invocation |
| `gh` | not installed |
| `jsonschema` | system package, 4.19.2 |

**The remotes differ by design.** The deploy key reaches the subnt repo
and nothing else; Atlas itself is still pulled anonymously over HTTPS and
the device cannot push to it. A commit that is not pushed from the
workstation is invisible to the device.

There is also a stale `/home/pi/github/atlas` clone at `first commit`
(2026-07-11) from an earlier layout. It is not the live checkout and
nothing reads it.

## Deploy

`subnt/systemd/atlas-subnt.{service,timer}`, a oneshot unit and a
six-hour timer offset to :55 so it lands after the fleet pass. It is its own
unit rather than an `ExecStartPost=-` on `atlas-fleet.service`, because
that unit runs the repo reconcile pass and a bug here writes to a public
site.

Install lines are in the service file.

## Tests

```
python3 -m unittest discover -s subnt/tests -t subnt/tests
```

Every test builds its own stores through the real modules' schema, so a
column that moves upstream breaks the tests rather than the device. None
touches a device, a network, or the real remote: the publish tests run
against a local temporary repository. The schema drift test reads
`$SUBNT_CHECKOUT`, else `~/src/github/vanlabs-dev/subnt`, else the
configured `checkout_dir`, and skips when none has a schema file.
