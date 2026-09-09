## Context

See `proposal.md` for motivation. The constraints that shape the approach:

- The page contract is frozen and accepted in another repo
  (`shinogi/openspec/specs/public-pulse/spec.md`). This design fills it and
  does not negotiate with it.
- Every fact already exists in stores that `telegram/atlas_briefing.py`
  reads. None of it exists as facts: the five section builders return
  `List[str]` formatted for Telegram, and `compose()`
  (`telegram/atlas_briefing.py:438`) appends `_atlas_section`, whose lines
  include the TaoStats quota and watermark staleness, plus a closing line
  that is either `next: pick mining.budget_band ...` or the LAN board URL.
- The stores live on the Pi. Only `var/fleet/www/` exists in this checkout,
  so compose cannot be exercised against real data off-device. Everything
  verifiable here must be verifiable against a fixture store.
- The Pi reaches Atlas by `git pull` in `/home/pi/atlas`, over HTTPS and
  anonymously. It holds no private SSH key, no `~/.gitconfig` and no
  credential helper, so it can read any public repo and write none. See
  "Plain `git`, never `gh`" below for what was found on the device.

## Goals / Non-Goals

**Goals:**

- One module that turns recorded rows into a contract-conforming document,
  testable end to end against a fixture store with no device.
- Leak-proof by construction and by assertion: the publish path refuses a
  document carrying operator material rather than trusting the composer.
- Additive to Atlas: no edit to `atlas_briefing.py` or
  `atlas_fleet_dashboard.py`, no new table in an existing store.

**Non-Goals:**

- Any change to the shinogi page contract or its look. The shell's CSS is
  the design; this change fills the bodies.
- The shinogi-side contract test change. It belongs in that repo.
- Enabling the push. That waits on the credential decision.
- Any second view, feed, history page, or archive of past editions.

## Decisions

### A top-level `shinogi/` directory, not a module under `telegram/`

The repo is one directory per capability: `fleet/`, `livedata/`,
`telegram/`, `knowledge/`, `repotrack/`, `triage/`, `hermes/`,
`inventory/`, `hardening/`. Publishing a public web page is not a Telegram
concern, and its systemd units, config, README and tests all want a home.

The handover argued that a sibling of `atlas_briefing.py` is lower friction
because the briefing readers are the dependency. That premise does not hold
here. Cross-directory import is the established pattern, used at
`fleet/atlas_fleet_mining.py:305` (fleet reaching `livedata/`),
`fleet/atlas_fleet_signals.py:1342` (same), `fleet/atlas_fleet_index.py:77`
(fleet reaching `repotrack/`) and `telegram/atlas_telegram.py:212`
(telegram reaching `inventory/`). It costs three lines, and this module
must reach both `telegram/` and `fleet/` regardless, so no single parent
directory removes the cost.

Layout:

```
shinogi/
  atlas_shinogi.py           facts, compose, render, publish, CLI
  config.json
  README.md
  systemd/atlas-shinogi.service
  systemd/atlas-shinogi.timer
  tests/test_shinogi.py
```

### Re-derive facts; never wrap `compose()`

The composer imports `_Sources`, `_movers` and `tg._release_for_upgrade`
and runs its own queries with the same SQL semantics and the same config
keys. It does not call `compose()`, any `_*_section` builder, or
`_to_messages`.

Alternative considered and rejected: call `compose()`, drop the `atlas`
section and the closing line, and convert the remaining lines to HTML. It
is less code and it is wrong. It inherits Telegram phrasing, it cannot
produce the attention section at all (the briefing has none), it cannot
carry per-figure deltas against the shinogi publish because the briefing's
deltas are already baked into its strings, and it leaks the moment a new
line is added upstream to a section this page renders. The leak surface
becomes "every future edit to `atlas_briefing.py`".

The cost is real: roughly the same query volume written twice, in two
modules, that can drift. Mitigated by sharing `_Sources` and `_movers`
rather than re-implementing them, and by naming the shared read points in
`shinogi/README.md`.

### The attention strip reuses `build_board`, discards its prose

`build_board` (`fleet/atlas_fleet_dashboard.py:398`) already does the work:
it runs the metrics report, resolves recently-changed econ netuids, scores
every active subnet through `score_subnet` (`:123`), and sorts descending.
The renderer calls it and reads only `row["netuid"]`, `sc["why"]` and
`sc["pure_opaque"]`, taking rows in the order `build_board` produced.

It ignores `thesis`, `detail`, `badges`, `evid`, `cue`, `cue_kind` and
`score`. `build_thesis` (`:195`) is never called by this module; it runs
inside `build_board` and its output is dropped. Reimplementing the scoring
to avoid that wasted call would fork the definition of attention, which is
worse than one unused string per subnet.

The public reason is a fixed map from the six recorded `why` tokens to
short phrases, defined in this module. `why` is closed by construction:
`score_subnet` returns one of `divergence`, `emission`, `abandon`,
`fresh`, `opaque`, `quiet`. An unmapped token renders as a named gap
rather than the raw token.

### The recorded name comes from `livedata.panel_snapshot.name`

The fleet metrics report rows carry `netuid` and `org` and no subnet name
(`fleet/atlas_fleet_metrics.py:863`). Two stores record an on-chain name:
`livedata.panel_snapshot.name` (written each gate pass,
`livedata/atlas_live.py:2929`) and `fleet.mine_econ.subnet_name` (written
by mining triage). Attention rows join the newest `panel_snapshot` row per
netuid, because that is the same store and the same pass the movers,
vitals and block number come from, so a name and a block on the same page
share an observation. The mining head keeps `mine_econ.subnet_name`, which
is what the briefing already uses (`telegram/atlas_briefing.py:345`).

A netuid with no name in either place renders the gap. It does not fall
back to `org`, which is a GitHub organisation and not the subnet's
recorded name.

### Publish state lives in its own store

`var/shinogi/shinogi.db`, one `meta` table: previous figure set as JSON,
previous publish time, last published content hash.

Alternative rejected: the notifier `meta` table, where the briefing keeps
`briefing:figures` (`telegram/atlas_briefing.py:45`). Sharing it would make
the public page's delta state a row in the Telegram ledger, and the
briefing's figures are keyed per edition kind on a daily and weekly clock.
Shinogi deltas must compare against the last shinogi publish, on a
six-hour clock, which is a different series. Keeping them apart also keeps
compose read-only against every existing store.

Figures are written only on a successful publish. A composed-but-unpublished
edition must not consume the comparison point, or the next real edition
would show deltas against a page nobody ever saw.

### Exclusion is asserted at publish, not trusted at compose

The module carries a deny list: the exact `OPERATOR_TOKENS` from
`shinogi/tests/test_page_contract.py` plus the wider off-page list from the
contract (wallet addresses, key material, Telegram identifiers, LAN
addresses, exploit paths, budget band, rent, hardware rung, health,
watermark, next-action). Publish scans the rendered document and fails
closed on a hit, writing nothing.

This is belt and braces on top of composing from facts. The failure mode it
guards is a store row that itself contains operator material, for example a
`what_changed` verdict string quoting a path or an address. The composer
cannot know that in advance; the scan can.

### The as-of line format

`as of YYYY-MM-DD HH:MM UTC · block N`, and when the block is missing,
`as of YYYY-MM-DD HH:MM UTC · block not recorded`. The contract says
"compose time in UTC" and fixes no pattern; minute resolution matches a
six-hour cadence.

Consequence: the first real edition produces the literal strings `as of `
and `block `, which `shinogi/tests/test_page_contract.py` currently asserts
are absent. That test must be widened in the shinogi repo before a real
edition can land green there. Recorded in Risks.

### The publish gate hashes the facts, not the timestamp

Found by task 6.10 while implementing, and it corrects an earlier claim in
this document that minute resolution preserves hash gating. It does not: at
six-hour cadence the minute changes on every pass, so a plain document hash
differs every time and the gate never holds. Shipping that would commit a
new timestamp over unchanged facts about 124 times a month and leave the
shinogi history useless as a record of what moved.

`fact_digest()` hashes the document with the as-of line normalised out, and
publish compares that. An edition is republished only when a fact it
reports actually moved. When nothing moved, the live page keeps the compose
time of the edition that is published, which is exactly what the contract
asks the as-of line to state.

Alternative considered and rejected: drop the compose time from the page so
the plain hash works. The contract requires it, and it is the one figure
that tells a reader how fresh the page is.

The specs' hash-gate requirement was amended to match before the code
landed.

### Its own oneshot service and timer

`atlas-fleet.service` runs the repo reconcile pass. Publishing a public
page is a different job with a different blast radius: a bug there writes
to a public site, and the operator must be able to stop it without
stopping fleet reconciliation.

The shinogi `AGENTS.md` "Next" section suggests `ExecStartPost=-…` on the
fleet unit. That note predates this design and needs updating in that repo.

`atlas-shinogi.timer` runs `OnCalendar=*-*-* 00/6:55:00` with a short
randomized delay. The fleet timer starts at `00/6:20` with
`RandomizedDelaySec=15m`, so the fleet pass begins between :20 and :35;
:55 puts the render after it, so `mine_econ` and `metric_activity` are the
current pass's. `livedata` is refreshed hourly and independently.

### Publish commits as `vanlabs-dev <vanlabs@pm.me>`

The handover says to author publish commits as `vaNlabs <vanlabs@pm.me>`.
That is the Atlas identity. Every commit in the shinogi repo is authored
`vanlabs-dev <vanlabs@pm.me>`, and its `AGENTS.md` states that name. The
publish keeps the target repo's own history consistent and uses
`vanlabs-dev <vanlabs@pm.me>`.

Identity is passed per invocation with `git -c user.name=... -c
user.email=...`, so the publish does not depend on the checkout's local
config being right and cannot be silently changed by it. No attribution
trailer, per both repos' rules.

### Plain `git`, never `gh`, and never able to prompt

The push is `git push` in the shinogi checkout. `gh` authenticates
separately from `git` and Atlas `AGENTS.md` requires confirming the active
account before any writing `gh` command, which a timer cannot do. `gh` is
not installed on the device anyway.

Checked on the device 2026-09-09, and it corrects what `AGENTS.md` says
about the remote:

- Atlas on the Pi is cloned from `https://github.com/vanlabs-dev/atlas.git`,
  **not** the SSH remote `AGENTS.md` describes. It pulls anonymously.
- `/home/pi/.ssh/` holds `authorized_keys` and `known_hosts` and **no
  private key**. `ssh -T git@github.com` from the Pi is
  `Permission denied (publickey)`, so an SSH remote cannot be used there
  without a new key.
- There is **no `/home/pi/.gitconfig`**: no `user.name`, no `user.email`,
  no credential helper. Passing identity per invocation with `git -c` is
  therefore required, not merely tidy; without it every commit would fail.

Consequence for the push: git must never be able to sit on a credential
prompt, or a oneshot unit would hang rather than fail. Every git call runs
with `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS`, `ssh -o BatchMode=yes`, stdin
closed, and a 120s timeout. Verified on the device: the push fails with
`could not read Username for 'https://github.com'` and returns.

## Risks / Trade-offs

- **The shinogi contract test fails on the first real edition.** It asserts
  `page.asof == ["awaiting first Atlas publish"]` and that `as of ` and
  `block ` are absent. A real edition contradicts all three. → Widen that
  test in the shinogi repo, in its own session, so it accepts both the
  shell and a published edition. Sequence it before the push is enabled;
  it does not block composing or writing.
- **No write credential on the Pi for `vanlabs-dev/shinogi`, and no way to
  make one without an operator decision.** The device holds no private SSH
  key and no git credential helper, and reaches GitHub over HTTPS
  anonymously. → The push ships disabled. Compose, render, write and hash
  comparison are implemented and verified without it. Creating or moving a
  credential is the operator's decision and is not part of this change.
- **Compose cannot be run against real data from this machine.** → Every
  test runs against a fixture store built in the test. The first real
  edition is verified on the Pi with the push still disabled, by reading
  the written file.
- **Two modules querying the same tables can drift.** → `_Sources` and
  `_movers` are imported, not copied. `shinogi/README.md` names every
  shared read point so a future change to the briefing's queries has a
  place that says who else reads them.
- **`build_board` is the expensive path**, running the full metrics report
  each pass. → It is the same cost `atlas-dashboard` already pays per fleet
  pass, at six-hour cadence, on a store already warm from the fleet run
  twenty minutes earlier.
- **`build_board` is called on a read-only connection.** If the metrics
  report writes anywhere, it will raise rather than mutate. → That is the
  wanted failure. A test opens a fixture store read-only and asserts
  `build_board` completes, so the assumption is checked and not assumed.
- **A first edition mostly of gaps.** → Correct behaviour, stated in the
  contract. Naming a missing input is the requirement; estimating is the
  defect.
- **Publish budget.** Six-hourly tops out near 124 Cloudflare Pages builds
  a month against 500 on Free, and fact-gating means an edition whose
  figures have not moved costs nothing at all.
- **A quiet network leaves the page's as-of time behind.** Fact-gating
  means the published compose time only advances when something moves. →
  Correct and honest: the time stated is the time the published edition was
  composed. The panel snapshot block on the same line shows how far the
  chain has run since.

## Migration Plan

1. Land the module, config, unit files, README and tests in Atlas, and
   **push `main` to GitHub**. The device pulls from
   `https://github.com/vanlabs-dev/atlas.git`, so a local commit is
   invisible to it; a commit that is not pushed makes step 2 a no-op and
   the module will not exist on the Pi.
2. `git pull` in `/home/pi/atlas`. Run `atlas_shinogi.py compose --dry-run`
   by hand and read the document it would write. Confirm the sections, the
   gaps, and the exclusion scan against real stores.
3. Clone `vanlabs-dev/shinogi` to `/home/pi/shinogi` over **HTTPS**
   (`https://github.com/vanlabs-dev/shinogi.git`), which is what the device
   can do today. The repo is public, so the clone needs no credential. An
   SSH remote would need a key the Pi does not have.
4. Widen the contract test in the shinogi repo.
5. Resolve the push credential with the operator.
6. Install the timer and service, publication still disabled, and confirm
   two passes write the expected file and report no change on the second.
7. Enable publication.

Rollback: `enabled: false` in `shinogi/config.json` stops compose and
publish and touches nothing else; `publish: false` stops only the write to
the checkout. Disabling the timer stops the pass. A failed push leaves the
last Cloudflare deploy live.

## Open Questions

- Whether `/home/pi/shinogi` is where the operator wants the second
  checkout. It mirrors `/home/pi/atlas` and is the assumption in the config
  and the unit files. Changing it is a config value, so it does not affect
  the specs or the task breakdown.
