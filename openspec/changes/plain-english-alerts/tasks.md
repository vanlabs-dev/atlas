# Tasks

## 1. Layout and units

- [x] 1.1 Move setting names, blocks, run ids, SHAs, file counts, raw values, sources and ISO times into the details fold in every builder. Cap key figures at two. Remove the `Before: stored value. After: stored value.` line and the repeated `Governs:` line. Verify with a test per class that the body outside the fold carries none of them.
- [x] 1.2 Add `unit: "u16-fraction"` to the `display` map for `CollateralLockShare` and `BasketConcentrationCap` and render percentages. Capitalise and de-duplicate `governs` text. Verify the `0% → 95%` and `6.25% → 12%` scenarios.
- [x] 1.3 Reword the `knowledge-ingestion` template to "already in use, nothing to do" and drop its `Next:` and microsecond timestamp. Verify a test on a staged-count fixture.
- [x] 1.4 Update `voice.lexicon`, `voice.gloss` and `telegram/docs/voice.md` section 2 for the plain terms (`reward cutoff`, `demand`, `version`). Verify the voice conformance test passes and a test that alert headlines hold none of the old terms.

## 2. Rewrite pass

- [x] 2.1 Add `message` to `message_event` output (`Message.to_dict()`) and a rebuild helper using `Message.from_dict`. Verify existing renderer tests pass unchanged.
- [x] 2.2 Write `telegram/atlas_plain_rewrite.py`: converter, `build_prompt` (fenced data, lexicon, fixed JSON shape), `parse_reply`, `rewrite` with injectable runner, per-event and per-scan time bounds. Verify with a stub runner: success, timeout, non-zero exit, unparseable reply, budget spent.
- [x] 2.3 Write `check_reply`: numbers, percentages, dates, `Subnet N` ids, subnet name, length, links, markup, em dash, `Next` with a command or path. Verify tests for the invented-number, changed-name, injected-instruction and em-dash scenarios, and that each real sample from the review page passes with its drafted proposal.
- [x] 2.4 Add the `rewrite_cache` table and the `events.rewrite` column (guarded `ALTER TABLE`). Verify a same-content second call makes no runner call, and an old DB migrates.
- [x] 2.5 Hook the pass into `notify_scan` after the tier and dedup checks, instant events only. Verify briefing and shadow events and deduped events make no call, and a Hermes-down run sends every alert from templates.
- [x] 2.6 Add the `rewrite` block to `telegram/config.json` (`enabled`, `toolset`, `timeout_seconds`, `scan_budget_seconds`, `next_allowed_classes`), disabled until the toolset is set. Add rewrite figures to `atlas_telegram.py status`. Verify `rewrite.enabled: false` restores template-only sending.
- [ ] 2.7 Run the pass against every real event from the 28-day replay on the Pi, read-only, no send. Verify the accept rate and read every refused and every accepted rewrite of the parameter and upgrade classes with the operator.

## 3. Behaviour changes

- [x] 3.1 Set `knowledge-ingestion` `tier` to `briefing` in `telegram/config.json`. Verify a scan test records `briefed` and sends nothing.
- [x] 3.2 Emit class `gate-crossing-no-effect` for `emission_enabled == 0`, register it `delivery_only` at `briefing`. Verify a test that it sends nothing, the cooldown and eligibility state of `gate-crossing` is untouched, and an emission-on crossing still pages.
- [x] 3.3 Allow an LLM `Next:` only for classes in `next_allowed_classes`. Verify a test that other classes drop a model-written `Next`.

## 4. CoinGecko schema

- [x] 4.1 Capture one live `simple/price` reply read-only and record it as a fixture. Verify the reply against `livedata/schemas/coingecko/simple-price.v1.schema.json` and name the missing field's cause.
- [x] 4.2 Repair the request or the schema, per the fixture. Verify a regression test against the fixture and the livedata suite.

## 5. Deploy

- [x] 5.1 Run every suite off-device. Verify telegram, livedata, upgrade, knowledge and repotrack are green.
- [ ] 5.2 After the push is approved, pull on the Pi, run every suite, set `rewrite.toolset` from `hermes tools list`, run `scan` with `rewrite.enabled` true against the replay. Verify the service `TimeoutStartSec` exceeds the scan budget.
- [ ] 5.3 Send one test per changed class to the real chat. Verify on a phone that buttons open, times show local, and the fold opens.
- [ ] 5.4 Record the change in `docs/decisions.md` and `README.md`, then watch `status` for a week: rewrite used, fallbacks by reason, added latency.
