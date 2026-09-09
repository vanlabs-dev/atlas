## 1. Module skeleton and config

- [x] 1.1 Create `shinogi/` with `atlas_shinogi.py`, `config.json`,
      `README.md`, `systemd/` and `tests/`, following the module shape used
      by `fleet/` and `telegram/`
- [x] 1.2 Add the lazy cross-directory imports for `telegram/` and `fleet/`
      using the `sys.path.insert(0, os.path.join(_REPO_ROOT, ...))` pattern
      already used at `fleet/atlas_fleet_mining.py:305` and
      `telegram/atlas_telegram.py:212`; import `_Sources`, `_movers` and
      `tg._release_for_upgrade` rather than copying them
- [x] 1.3 Write `shinogi/config.json`: `enabled`, `publish`, the four store
      paths matching the `briefing` keys, `stale_hours` 26,
      `checkout_dir` `/home/pi/shinogi`, `state_db`
      `var/shinogi/shinogi.db`, and a rollback comment in the style of
      `telegram/config.json`. `page_url` was dropped: nothing in the module
      reads it and dead config is worse than none
- [x] 1.4 Add the publish-state store: `var/shinogi/shinogi.db` with a
      `meta` table, created on first use, holding the previous figure set,
      previous publish time and last content hash

## 2. Fact layer

- [x] 2.1 Network facts: runtime spec from `livedata.meta.last_live_spec`
      with its release subject through `_release_for_upgrade`;
      `chain_param_events` in the window; `gate_state` bar with the 26h
      stale bound and a stale result that carries the observation time
      instead of the figure; `gate_events` side-change count;
      newest `network_vitals` row with its date
- [x] 2.2 Mover facts: reuse `_movers` over `moving_price_tao` and `share`
      at the configured thresholds, carrying from and to values with both
      reference blocks; newest-row `dereg_risk_level = 'high'`, contested
      or takeover-eligible netuids, and `gate_sides.hovering` as a count
      with netuids
- [x] 2.3 Mining facts: newest `mine_econ` pass; head netuid and
      `subnet_name`; ranked, cut and observed counts; top-ten membership
      entered and left against the previous edition. Do not read
      `rent_band` and do not emit a budget-band, rent or hardware line
- [x] 2.4 Attention facts: call `build_board` on a read-only fleet
      connection, take rows in its order, drop `pure_opaque`, cap at ten,
      and keep only `netuid`, `why` and the joined newest
      `panel_snapshot.name`; map the six `why` tokens to short public
      phrases and render an unmapped token as a gap
- [x] 2.5 Code and narrative facts: seven-day push count from the newest
      `metric_activity` pass (`c7 > 0` over the pass), `high`
      `signal_econ_verdicts` in the window with netuid, verdict line and
      commit, the `med` count, `epochs` re-points, `signal_adoptions`
      where `kind = 'model-id'`, and `signal_events` narrative clusters
- [x] 2.6 Newest `panel_snapshot.block_number` for the as-of line, and the
      gap result when no snapshot block exists
- [x] 2.7 Make every fact function return a named gap for an absent store,
      an absent table or an empty result, and never raise for either

## 3. Compose and render

- [x] 3.1 Compose: resolve the window from the previous publish time, or
      the six hours before compose on a first edition; load the previous
      figure set; assemble the five sections plus the as-of facts; return
      the edition and its new figure set without writing anything
- [x] 3.2 Deltas against the previous shinogi figure set only, with a
      first-edition statement and no figure deltas when none is stored.
      Do not read the notifier ledger
- [x] 3.3 Render: emit the shell's exact HTML shape and CSS from
      `shinogi/index.html`, with `<h1>SHINOGI</h1>`, the tagline, a
      `<div class="asof">`, the five `<section id=...>` landmarks in the
      contract order, and `Code` and `Narrative` `<h3>` groups inside the
      last. Escape every interpolated value
- [x] 3.4 As-of line as `as of YYYY-MM-DD HH:MM UTC · block N`, and
      `· block not recorded` when the block is missing
- [x] 3.5 Keep every landmark on an edition with no facts at all, each
      body naming its missing input

## 4. Exclusion scan

- [x] 4.1 Define the deny list: the exact `OPERATOR_TOKENS` from
      `shinogi/tests/test_page_contract.py` plus the contract's wider
      off-page list (wallets, key material, Telegram identifiers, LAN
      addresses, exploit paths, budget band, rent, hardware rung, atlas
      health, watermark, next-action)
- [x] 4.2 Scan the rendered document before any write and fail the pass
      closed on a hit, naming the token and writing nothing
- [x] 4.3 Assert the self-contained rules in the same scan: no script
      element, no external stylesheet, font or link, no `@import`, no
      `fetch(`, no `XMLHttpRequest`

## 5. Publish

- [x] 5.1 Write the rendered document into the checkout atomically, after
      the scan passes
- [x] 5.2 Fact-gate: compare the rendered content against the committed
      `index.html` with the as-of line normalised out, and make no commit
      and no push when equal, reporting no change. Hashing the whole
      document never holds the gate, because the compose time moves on
      every pass (found in 6.10; specs and design amended to match)
- [x] 5.3 Commit with `git -c user.name=vanlabs-dev -c
      user.email=vanlabs@pm.me`, subject in the repo's style, no
      attribution trailer; push over the SSH remote with plain `git`, never
      `gh`
- [x] 5.4 Fail closed with a named reason when the checkout is missing, is
      not a repository, is dirty, or has no usable push credential; leave
      the checkout unchanged and create or move no credential
- [x] 5.5 Persist the new figure set, publish time and content hash only
      after a successful publish
- [x] 5.6 CLI: `compose --dry-run` prints the document and the scan result
      and writes nothing; `publish` runs the full pass; both honour
      `enabled` and `publish` in config

## 6. Tests

- [x] 6.1 Fixture store builder: create the four stores in a temp dir with
      the tables and columns the fact layer reads, so every test runs with
      no device and no network
- [x] 6.2 Contract shape: landmark ids and order, `<h1>SHINOGI</h1>`, the
      `asof` div, the two `<h3>` groups, using the same parse the shinogi
      contract test uses
- [x] 6.3 Empty edition: no store at all still renders five landmarks,
      each naming its missing input, and the pass reports success
- [x] 6.4 Stale bounds: a 27h-old gate row renders the bar stale with its
      time and no theta; a 20h-old vitals row renders its figures with its
      date and is not called stale
- [x] 6.5 Deltas: first edition states so and shows none; a second edition
      compares against the stored shinogi figure set; a composed but
      unpublished edition leaves the stored set unchanged
- [x] 6.6 Attention: ordering follows `build_board`, `pure_opaque` rows are
      absent, the cap holds at ten, a missing name renders a gap, and no
      score, cue glyph or thesis string appears
- [x] 6.7 Push count is read from the stored seven-day fact and not
      recomputed over the window
- [x] 6.8 Exclusion: a store row seeded with an operator token fails the
      pass closed and writes nothing
- [x] 6.9 `build_board` completes against a read-only fixture connection,
      proving the metrics report performs no write
- [x] 6.10 Publish: unchanged content makes no commit; changed content
      commits under `vanlabs-dev <vanlabs@pm.me>` with no trailer; a
      missing checkout fails closed. Use a local temp repository, never
      the real remote

## 7. Docs and device

- [x] 7.1 `shinogi/README.md`: what the module reads, every shared read
      point in `telegram/atlas_briefing.py` and
      `fleet/atlas_fleet_dashboard.py`, the config keys, the rollback, and
      the one-direction rule
- [x] 7.2 `docs/decisions.md`: the module location, the own-unit choice
      over `ExecStartPost=-` on the fleet unit, the separate publish-state
      store, and the `vanlabs-dev` publish author against the handover's
      `vaNlabs`
- [x] 7.3 `README.md`: status line and a `shinogi-publish` row in the
      capability table
- [x] 7.4 `systemd/atlas-shinogi.service` and `.timer`: oneshot as `pi` in
      `/home/pi/atlas`, `OnCalendar=*-*-* 00/6:55:00` with a short
      randomized delay, `Persistent=true`, and the install comment block
      copied from `fleet/systemd/atlas-fleet.service`
- [x] 7.5 Propose to the operator, do not run: the `/home/pi/shinogi`
      clone, the unit install, and the credential decision that gates
      enabling the push (proposed in the session summary; commands are for
      the operator to run)
