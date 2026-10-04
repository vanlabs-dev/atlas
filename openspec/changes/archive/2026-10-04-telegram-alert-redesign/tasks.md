# Tasks

## 1. Fixtures and message model

- [x] 1.1 Capture the 2026-10-04 Pi samples (every class, both pulse editions, probe drift) as read-only fixtures under `telegram/tests/fixtures/`. Verify each fixture loads in a test without network access.
- [x] 1.2 Add the `Message` dataclass, `rec()` sentinel stripping, and `severity_for()` (design D1, D8) to `telegram/atlas_telegram.py`. Verify unit tests cover every row of the D8 table.
- [x] 1.3 Add `fmt_int`, `fmt_pct`, `fmt_tao`, `fmt_usd`, `fmt_change`, and `fmt_time` (D4, D5). Verify unit tests: `0.008581` gives `0.858%`, `9197096` gives `9,197,096`, an ISO timestamp gives a `tg-time` entity with a UTC fallback, and an unparseable time is marked `dated`.
- [x] 1.4 Add `subnet_names`, `subnet_label`, and `subnet_tag` (D6). Verify tests: name present, name missing, name `Unknown`, and HTML metacharacters escaped.

## 2. Renderer and transport

- [x] 2.1 Rewrite `render_html` and `render_plain` over `Message` with the D3 shrink order and D2 gloss scope. Verify tests: headline never glossed, recorded text never glossed, fold shrinks first, headline and `Next:` survive a 3,500-character overflow, and tags stay balanced.
- [x] 2.2 Extend `send_message` and `deliver_event` with `reply_markup` buttons and `link_preview_options` (D7). Keep buttons on the 400 plain fallback, and add the final resend without buttons. Verify with poster-stub tests on the request payload; no `disable_web_page_preview` may remain.
- [x] 2.3 Add the `links` templates to `telegram/config.json` and a URL builder that omits a button on a missing key. Verify a test with a missing template sends without that button.

## 3. Notifier classes

- [x] 3.1 Rebuild `chain_runtime_upgrade_events` in the house layout: release subject or "not matched", governance line, releases button. Verify `test_notifier` upgrade cases and a fixture golden-structure test.
- [x] 3.2 Rebuild `_render_param_event`: subnet number and name in the headline for single-subnet items (bug fix), plain effect sentences, undescribed-parameter `Next:`, taostats button. Verify with `test_chain_params_class` plus a new `SubnetEmissionEnabled[82]` single-row test.
- [x] 3.3 Rebuild `gate_crossing_events`: name, price at the event block (D11), "Nth largest share" wording, cause line, severity by direction and emission flag. Verify with `test_gate_class`; tier, cooldown, and eligibility tests must stay unchanged and pass.
- [x] 3.4 Rebuild `_build_repo_event` and `_build_digest_event`: plain live-or-not sentence, deduplicated commit subjects (bug fix) with prefixes stripped, area names in the body, counts in the fold, compare button. Verify the breakdown tests, rewritten as structural assertions, plus a duplicate-subject test.
- [x] 3.5 Set `classes.narrative-cluster.tier` to `shadow` in `telegram/config.json`. Verify a test that a cluster event is recorded `shadowed` and no send happens.
- [x] 3.6 Rebuild the fleet builders (cluster, watchlist, econ, signal digest) with panel names, one digest item per line, merged same-subnet items, and commit buttons. Verify with `test_fleet_signals_class`; dedup-key tests stay unchanged.
- [x] 3.7 Rebuild schema-drift, knowledge-ingestion (full `activate` command in `pre`), subnet-registry, fail-closed, and the CLI test alert (em dash removed). Verify with `test_notifier` class cases and a repo-wide grep for `—` in `telegram/` output strings.
- [x] 3.8 Update `telegram/tests/test_voice.py` to the new canon: marker first, gloss in prose only, `Next:` last, no `SN`, no em or en dash, over every class fixture. Verify `python3 -m unittest discover -s telegram/tests` passes.

## 4. Pulse briefing

- [x] 4.1 Replace the section builders per D10: network, rules with set-then-reset merging, price and share moves (top 3, no blocks), watch (top 3 non-immune by prune rank, plus at the bar), high impact (named, high only), health fold. Delete the narrative and mining sections from the briefing only. Verify `test_briefing` cases for each spec scenario, including "critical subnets are not dropped" and "immune excluded".
- [x] 4.2 Add the ☀️ / 🗓️ edition headers, `_summary_line`, and the new packer: no board link, fold last, D10 drop order, network never cut. Verify `test_briefing` truncation and closing-line tests, rewritten to the new spec.
- [x] 4.3 Run `python3 -m unittest discover -s subnt/tests`. Verify subnt still passes with the shared helpers unchanged.

## 5. Probe and upgrade reports

- [x] 5.1 Convert `livedata/atlas_probe.py` to `drift_message` and a `Message`-based `telegram_send` with HTML and the 400 fallback (D9). Verify the probe tests in `livedata/tests` (watch paging once per failing set, cleared note) pass with the new wording.
- [x] 5.2 Convert every `upgrade/atlas_upgrade.py` report (waiting, updated, dry run, retrying, blocked, stalled) to `Message`, with the commit button and the error tail in a `pre` fold. Verify `upgrade/tests/test_upgrade.py`; one-report-per-outcome and pending-report retry tests are unchanged.

## 6. Docs

- [x] 6.1 Update `telegram/docs/voice.md` (layout rules, severity marker, gloss scope, `Subnet N (Name)` and `Name (N)` forms) and the lexicon conformance test. Verify the conformance test passes against the edited canon.
- [x] 6.2 Update `telegram/README.md` (message layout, buttons, briefing sections) and record the decision in `docs/decisions.md`. Verify the docs mention no removed briefing section.

## 7. Integration

- [x] 7.1 Run every suite: `telegram`, `livedata`, `upgrade`, `subnt`, `fleet`. Verify all pass.
- [x] 7.2 On the Pi after the pull, render one message per class read-only from the live stores, plus `atlas_telegram.py test --class schema-drift` to the real chat. Verify on the phone: buttons open, times show local, nothing is truncated.
