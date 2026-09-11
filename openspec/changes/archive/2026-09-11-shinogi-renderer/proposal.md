# Shinogi Renderer

## Why

`https://shinogi.dev` is live and serves a shell. Its as-of line reads
`awaiting first Atlas publish` and all five sections read
`Awaiting first Atlas publish`. The page contract is frozen and accepted
(`shinogi/openspec/specs/public-pulse/spec.md`, 2026-09-02), and nothing
writes to it. A case-insensitive search for `shinogi` across this repo
returns zero hits outside `.git` and `var`.

Atlas already holds every fact the contract asks for, in stores the pulse
briefing reads read-only each day:

| Contract section | Store rows already recorded |
|---|---|
| Network | `livedata.meta.last_live_spec`, `chain_param_events`, `gate_state`, `gate_events`, `network_vitals` |
| Movers | `panel_snapshot` (`moving_price_tao`, `share`, `dereg_risk_level`, `conviction_is_contested`, `takeover_eligible`), `gate_sides.hovering` |
| Mining | `fleet.mine_econ` (`netuid`, `subnet_name`, `cut_reason`, `net_tao_month`) |
| Attention | `fleet` metrics report plus `score_subnet` |
| Code / narrative | `fleet.metric_activity.c7`, `signal_econ_verdicts`, `epochs`, `signal_adoptions`, `signal_events` |

The gap is not data. It is that the only consumer of those facts is
`telegram/atlas_briefing.py`, whose section builders return formatted
operator lines (`List[str]`), not facts. `compose()` closes with a next
action or the LAN board URL, and `_atlas_section` emits the TaoStats
quota and watermark staleness. Wrapping it and dressing the result in
HTML would publish `192.168.0.150:8480`, `TaoStats quota`, and
`next: pick mining.budget_band` to the open internet. The shinogi
contract test bans those exact strings by name.

So the renderer is a second reader over the same stores, not a wrapper.

## What Changes

- **A new top-level `shinogi/` directory.** One capability, one
  directory, matching `fleet/`, `livedata/`, `telegram/`, `knowledge/`
  and `repotrack/`. Cross-directory reuse is the established
  `sys.path.insert(0, os.path.join(_REPO_ROOT, ...))` pattern already
  used at `fleet/atlas_fleet_mining.py:305`,
  `fleet/atlas_fleet_signals.py:1342` and `telegram/atlas_telegram.py:212`.
- **A fact layer, not a line layer.** The composer reuses `_Sources`
  (`telegram/atlas_briefing.py:82`), `_movers` (`:192`) and
  `tg._release_for_upgrade`, and re-derives each section as structured
  facts with the same SQL semantics the briefing uses. Every figure keeps
  its reference block or observation date. Nothing formatted for Telegram
  crosses into the page.
- **The attention strip reuses the board's scoring, not its prose.**
  `build_board` (`fleet/atlas_fleet_dashboard.py:398`) already scores
  every active subnet through `score_subnet` (`:123`) and sorts
  descending. The renderer takes `netuid`, `score` ordering, `why` and
  `pure_opaque` from it and discards `thesis`, `cue`, `cue_kind`,
  `badges` and `detail`. `build_thesis` (`:195`) is board chrome and
  never reaches the page.
- **The recorded name is joined, not invented.** The fleet metrics report
  rows carry `netuid` and `org` and no subnet name
  (`fleet/atlas_fleet_metrics.py:863`). The recorded on-chain name lives
  in `livedata.panel_snapshot.name` and `fleet.mine_econ.subnet_name`.
  Attention rows join the newest `panel_snapshot.name` per netuid; a
  netuid with no recorded name renders the gap and no invented name.
- **Per-input stale bounds, not a blanket window.** The emission-gate bar
  uses the briefing `stale_hours` default of 26. Network vitals carry
  their observation date and are never called stale for age alone. Panel
  movers use the window since the previous shinogi publish, or the six
  hours before compose on a first edition.
- **A publish-state store, separate from the notifier.** A new
  `var/shinogi/shinogi.db` holds the previous edition's figures, the last
  publish time and the last content hash. The briefing's figure set lives
  in the notifier `meta` table under `briefing:figures`
  (`telegram/atlas_briefing.py:45`); shinogi deltas must compare against
  the last shinogi publish, not the last Telegram edition, so it keeps
  its own. The notifier ledger is not written.
- **A hash-gated publish.** `index.html` is written into the Pi's shinogi
  checkout, its content hash compared against the committed file, and the
  commit and push happen only on a change. Author `vaNlabs
  <vanlabs@pm.me>`, no attribution trailer.
- **Its own oneshot service and timer.** `atlas-fleet.service` runs the
  repo reconcile pass; publishing a public page is a different job with a
  different failure mode and must be disableable on its own. The timer
  runs six-hourly, offset to land after the fleet pass has refreshed
  `mine_econ` and `metric_activity`.
- **The push stays disabled until the operator resolves the credential.**
  Compose and write are enabled; the push is gated by config and by the
  absence of a write credential for `vanlabs-dev/shinogi` on the Pi.

Out of scope: the shinogi-side contract test change (it belongs in that
repo and its own session), any chain call, any provider call, any model
call, any read of shinogi by Atlas.

## Capabilities

### New Capabilities

- `shinogi-publish`: composing a public edition from recorded store facts
  under per-input stale bounds; the operator-token exclusion that makes it
  publishable; edition state and deltas against the previous shinogi
  publish rather than the Telegram briefing; and the hash-gated,
  one-direction publish to the shinogi checkout.

### Modified Capabilities

None. The renderer is a read-only second consumer of stores that
`live-data`, `fleet-signals`, `fleet-rotation-metrics`, `mining-triage`
and `telegram-integration` already specify. No existing requirement
changes.

## Impact

- **Code:** new `shinogi/atlas_shinogi.py` (facts, compose, publish, CLI),
  `shinogi/config.json`, `shinogi/README.md`,
  `shinogi/systemd/atlas-shinogi.{service,timer}`, `shinogi/tests/`.
  No edit to `telegram/atlas_briefing.py` or
  `fleet/atlas_fleet_dashboard.py`: both are imported, neither is changed.
- **Schema:** one new store, `var/shinogi/shinogi.db`, with a `meta`
  table. No existing store gains a table or a column. Every existing
  store is opened `mode=ro` through `tg.open_source_ro`.
- **Tests:** compose against a fixture store (section presence, gap
  naming, stale bounds, delta behaviour on first and later editions),
  the operator-token exclusion list, and the HTML shape the shinogi
  contract test asserts (landmark order, `<h1>SHINOGI</h1>`,
  `<div class="asof">`, two `<h3>` groups, no script, no external asset).
- **Docs:** `README.md` status and capability table, `shinogi/README.md`,
  `docs/decisions.md` for the module location and the publish-state store.
- **Device:** one `git pull`; a second checkout at `/home/pi/shinogi`; one
  new oneshot unit and timer; no new port, provider, credential or model.
  At six-hourly cadence the publish tops out near 124 Cloudflare Pages
  builds a month against the Free tier's 500.
- **Reversibility:** `enabled: false` in `shinogi/config.json` stops
  compose and publish and touches nothing else. The push is separately
  gated. Deleting `var/shinogi/shinogi.db` costs one edition's deltas.
- **Blocked:** the Pi has no write credential for `vanlabs-dev/shinogi`.
  Compose, write and hash comparison can land and be verified without it;
  enabling the push cannot. That decision is the operator's.
