# subnt: the public edition

OpenSpec change `subnt-renderer`. Composes the public
[subnt.dev](https://subnt.dev) page from rows already persisted in the
livedata and fleet stores, all opened read-only, and publishes it into a
second checkout when a fact on the page has moved.

Composing makes no chain call, no provider call and no model call. Every
figure traces to a stored row and carries its reference block or its
observation date. An input that is missing, or past its own stale bound, is
named on the page instead of estimated.

The publish path is one direction only. **Atlas writes subnt; subnt is
never read back.** No file in the checkout other than the published
document is touched, and none of it is an input to an edition.

## Why this is a second reader, not a wrapper

`telegram/atlas_briefing.py` reads the same stores, but its five section
builders return `List[str]` formatted for Telegram, and `compose()` appends
`_atlas_section` (the provider quota, watermark staleness) and closes with
either the LAN board URL or `next: pick mining.budget_band`. Dressing those
lines in HTML would publish the board address and the budget-band prompt to
the open internet, which is exactly what
`subnt/tests/test_page_contract.py` bans by name.

So this module re-derives each section as facts, with the same SQL
semantics, and shares the read primitives rather than the line builders.

## Shared read points

Change any of these and this module is a caller you must check.

| Shared from | Used for |
|---|---|
| `telegram/atlas_briefing.py` `_Sources` | opening the four stores read-only |
| `telegram/atlas_briefing.py` `_movers` | ranking price and demand-share movers |
| `telegram/atlas_briefing.py` `_table`, `_one`, `_delta_pct` | store probing and figure deltas |
| `telegram/atlas_telegram.py` `_release_for_upgrade` | the release subject for a runtime spec |
| `telegram/atlas_telegram.py` `resolve`, `open_source_ro` | path resolution and read-only opens |
| `fleet/atlas_fleet_dashboard.py` `build_board` | attention scoring and ordering |
| `fleet/atlas_fleet.py` `load_config` | the fleet config `build_board` needs |

`build_thesis`, `build_badges`, the cue glyphs and the numeric score are
board chrome. `build_board` produces them; this module drops them.

## What each section reads

| Section | Rows |
|---|---|
| Network | `livedata` `meta.last_live_spec`, `chain_param_events`, `gate_state`, `gate_events`, `network_vitals` |
| Subnet movers | `livedata` `panel_snapshot`, `gate_sides.hovering` |
| Mining | `fleet` `mine_econ` (never `rent_band`) |
| Attention | `fleet` metrics report through `build_board`, names joined from `livedata` `panel_snapshot.name` |
| Code | `fleet` `metric_activity.c7`, `signal_econ_verdicts`, `epochs` |
| Narrative | `fleet` `signal_adoptions` (`kind = 'model-id'`), `signal_events` |
| As-of block | `livedata` `MAX(panel_snapshot.block_number)` |

The fleet metrics report carries `netuid` and `org` and no subnet name, and
`org` is a GitHub organisation, not the recorded name. A netuid with no
recorded name renders that gap.

## What the page looks like

One full-bleed page, desktop first (`min-width: 1100px`, no mobile
breakpoints). Inter and JetBrains Mono from Google Fonts, a sticky masthead
carrying the as-of line, a hero stating the largest recorded movement beside
four stat tiles, then the five sections on a 2:1 grid.

Charts are inline SVG computed in this module from recorded series. No
library, no script, no browser call, so the page still reads with scripting
off:

| Chart | Series |
|---|---|
| Bar and TAO sparklines | `gate_state.theta`, `network_vitals.tao_usd` |
| Demand share across the bar universe | newest `panel_snapshot.share` per netuid, sorted, log scale, with the emission-gate rank marked |
| Mover detail | that netuid's recent `panel_snapshot` readings |
| Meters | subnet share of stake, ranked of observed, push coverage |

A chart introduces no figure the page does not otherwise report, and never
estimates, interpolates or smooths. A series with fewer than two recorded
points renders nothing rather than a misleading flat line.

The contract requires the page to be readable with scripting disabled and
bans any browser data fetch. It permits a typeface and presentation script.

## The as-of line carries the reader's own clock

The line states UTC, and a reader outside it cannot tell at a glance how old
an edition is. The masthead therefore carries an empty
`<time class="ago" datetime=...>` beside the pill, filled in the browser by
the one inline script on the page: "6 hours ago", with the reader's local
time on hover. It is presentation only and pulls nothing; with scripting off
it renders nothing and the absolute line stands alone.

A relative string fixed at compose would be wrong by the second view, because
an edition sits until a fact moves. Two constraints shape where it lives:

- It is a **sibling** of the `.asof` div, not a child. The contract's parser
  counts any element inside that div as nesting and would then read the
  as-of text off the wrong closing tag.
- `fact_digest()` normalises **both** the as-of line and that element's
  `datetime`. The instant sits outside the div the line normalisation
  covers, so missing it would republish unchanged facts every pass.

## Attention is grouped, and its reason is derived

`score_subnet` returns a category, and on the real fleet **93 of 106 public
rows carry the same one**. One phrase per category therefore rendered ten
identical lines that told a reader nothing.

`why_phrase()` derives the phrase from the score's own components
(`div_signed`, `cold`, `econ_fresh`, `pulse_spike`), stating direction in
words. `group_attention()` then collapses rows that share a reason, so the
repetition is stated once with a count and the exceptions stand out.

The contract bans the numeric score, direction-cue glyphs and the board
thesis sentence. It does not ban direction stated in words, and a test
asserts no derived phrase contains a digit or a glyph.

## Stale bounds are per input

- **Emission-gate bar**: 26 hours (`stale_hours`, the briefing default).
  Past it, the bar is named stale and its theta is not shown as current.
- **Network vitals**: shown with their observation date. A daily row is
  never called stale for age alone.
- **Panel movers**: the window since the previous subnt publish, or
  `window_hours` before compose when there is no previous publish.

## Editions and deltas

Deltas compare against the **previous subnt publish**, never against the
Telegram briefing watermark. The figure set, the publish time and the
content hash live in this module's own store, `var/subnt/subnt.db`.
They are written only after a successful publish, so a composed but
unpublished edition does not consume the comparison point.

The first edition says so and shows no figure deltas.

## The publish gate is on the facts

The as-of line carries the compose time, which moves on every pass. Hashing
the whole document would therefore never hold the gate: it would commit a
new timestamp over unchanged facts about 124 times a month. `fact_digest()`
hashes the document with the as-of line normalised out, so an edition is
republished only when something it reports has moved. A page left in place
keeps the compose time of the edition that is published, which is what the
contract asks the line to state.

## Before any write

The rendered document is scanned for operator material, for any call that
would fetch data in the browser, and for any external asset that is not a
typeface source. A hit fails the pass closed and writes nothing. The guarded case is a stored row that itself carries operator
material, for example a verdict line quoting a path or an address: the
composer cannot know that in advance, the scan can.

`OPERATOR_TOKENS` opens with the exact strings the subnt contract test
bans, then the wider off-page list.

## Commands

```
python3 subnt/atlas_subnt.py compose --dry-run     # print, write nothing
python3 subnt/atlas_subnt.py compose --out /tmp/index.html
python3 subnt/atlas_subnt.py publish               # the full pass
```

`compose` prints the document on stdout and a summary (scan result, byte
count, both hashes, window start, as-of block) on stderr. It exits 2 when
the scan finds anything.

## Config

`subnt/config.json`. Rollback: `enabled: false` stops compose and publish
and touches nothing else; `publish: false` composes and reports where it
would have written, but writes nothing.

| Key | Meaning |
|---|---|
| `enabled` | master switch for the pass |
| `publish` | write, commit and push; `false` composes only |
| `checkout_dir` | the subnt checkout the page is written into |
| `state_db` | this module's own store, for deltas and the publish hash |
| `commit_name` / `commit_email` | passed per invocation with `git -c`; the device has no `~/.gitconfig` |
| `window_hours` | the mover window on a first edition |
| `stale_hours` | the emission-gate bar bound |
| `attention_rows` | the attention cap |
| `live_db` / `fleet_db` / `repo_db` / `knowledge_db` | the stores, read-only |

## Failure modes

Every one of these fails the pass closed and leaves the checkout unchanged:
a missing checkout, a checkout that is not a repository, a dirty checkout,
a scan hit, and a push with no usable write credential. A failed push
leaves the local commit in place and the last Cloudflare deploy live;
recovering it is the operator's call, and this module does not reset.

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
The renamed service published successfully and `atlas-subnt.timer` is enabled.
All 75 renderer tests passed on the device. Cloudflare serves the exact
published edition at https://subnt.dev over valid HTTPS; unknown paths
return HTTP 404. The domain cutover is complete; `www` is not configured. See
`docs/subnt-rename.md` in the public-page repository for the cutover record.

| | |
|---|---|
| Atlas checkout | `/home/pi/atlas`, remote `https://github.com/vanlabs-dev/atlas.git`, pulls anonymously |
| subnt checkout | `/home/pi/subnt`, remote `git@github.com:vanlabs-dev/subnt.git` |
| Publish credential | a write-scoped deploy key for the subnt repo alone, `~/.ssh/id_ed25519_subnt`, selected by a `Host github.com` entry with `IdentitiesOnly yes` |
| `~/.gitconfig` | does not exist, which is why identity is passed per invocation |
| `gh` | not installed |

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
against a local temporary repository.
