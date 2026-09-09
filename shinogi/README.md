# shinogi: the public edition

OpenSpec change `shinogi-renderer`. Composes the public
[shinogi.dev](https://shinogi.dev) page from rows already persisted in the
livedata and fleet stores, all opened read-only, and publishes it into a
second checkout when a fact on the page has moved.

Composing makes no chain call, no provider call and no model call. Every
figure traces to a stored row and carries its reference block or its
observation date. An input that is missing, or past its own stale bound, is
named on the page instead of estimated.

The publish path is one direction only. **Atlas writes shinogi; shinogi is
never read back.** No file in the checkout other than the published
document is touched, and none of it is an input to an edition.

## Why this is a second reader, not a wrapper

`telegram/atlas_briefing.py` reads the same stores, but its five section
builders return `List[str]` formatted for Telegram, and `compose()` appends
`_atlas_section` (the provider quota, watermark staleness) and closes with
either the LAN board URL or `next: pick mining.budget_band`. Dressing those
lines in HTML would publish the board address and the budget-band prompt to
the open internet, which is exactly what
`shinogi/tests/test_page_contract.py` bans by name.

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

## Stale bounds are per input

- **Emission-gate bar**: 26 hours (`stale_hours`, the briefing default).
  Past it, the bar is named stale and its theta is not shown as current.
- **Network vitals**: shown with their observation date. A daily row is
  never called stale for age alone.
- **Panel movers**: the window since the previous shinogi publish, or
  `window_hours` before compose when there is no previous publish.

## Editions and deltas

Deltas compare against the **previous shinogi publish**, never against the
Telegram briefing watermark. The figure set, the publish time and the
content hash live in this module's own store, `var/shinogi/shinogi.db`.
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

The rendered document is scanned for operator material and for the page
contract's self-contained rules. A hit fails the pass closed and writes
nothing. The guarded case is a stored row that itself carries operator
material, for example a verdict line quoting a path or an address: the
composer cannot know that in advance, the scan can.

`OPERATOR_TOKENS` opens with the exact strings the shinogi contract test
bans, then the wider off-page list.

## Commands

```
python3 shinogi/atlas_shinogi.py compose --dry-run     # print, write nothing
python3 shinogi/atlas_shinogi.py compose --out /tmp/index.html
python3 shinogi/atlas_shinogi.py publish               # the full pass
```

`compose` prints the document on stdout and a summary (scan result, byte
count, both hashes, window start, as-of block) on stderr. It exits 2 when
the scan finds anything.

## Config

`shinogi/config.json`. Rollback: `enabled: false` stops compose and publish
and touches nothing else; `publish: false` composes and reports where it
would have written, but writes nothing.

| Key | Meaning |
|---|---|
| `enabled` | master switch for the pass |
| `publish` | write, commit and push; `false` composes only |
| `checkout_dir` | the shinogi checkout the page is written into |
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

**It creates and moves no credential.** That is an operator decision.

## Device reality (checked 2026-09-09)

`AGENTS.md` describes the Atlas remote as SSH. On the Pi it is not:

| | |
|---|---|
| Atlas checkout | `/home/pi/atlas`, remote `https://github.com/vanlabs-dev/atlas.git`, pulls anonymously |
| Pi SSH keys | none; `~/.ssh/` holds only `authorized_keys` and `known_hosts` |
| `ssh -T git@github.com` from the Pi | `Permission denied (publickey)` |
| `~/.gitconfig` | does not exist |
| `gh` | not installed |

So the shinogi checkout is cloned over HTTPS (the repo is public, no
credential needed) and **the push cannot authenticate at all** until the
operator provides a credential. `publish` stays `false` until then.

There is also a stale `/home/pi/github/atlas` clone at `first commit`
(2026-07-11) from an earlier layout. It is not the live checkout and
nothing reads it.

## Deploy

`shinogi/systemd/atlas-shinogi.{service,timer}`, a oneshot unit and a
six-hour timer offset to :55 so it lands after the fleet pass. It is its own
unit rather than an `ExecStartPost=-` on `atlas-fleet.service`, because
that unit runs the repo reconcile pass and a bug here writes to a public
site.

Install lines are in the service file.

## Tests

```
python3 -m unittest discover -s shinogi/tests -t shinogi/tests
```

Every test builds its own stores through the real modules' schema, so a
column that moves upstream breaks the tests rather than the device. None
touches a device, a network, or the real remote: the publish tests run
against a local temporary repository.
