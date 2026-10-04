# Proposal

## Why

Atlas Telegram messages name the mechanism instead of the effect. They
carry raw ISO timestamps, unformatted numbers, and bare netuids. Glosses
are injected into headlines and into recorded commit text. A review on
2026-10-04 rendered every message from live Pi data next to a proposed
rewrite (artifact `https://claude.ai/artifact/M9mbpJZX3Q7diUfVf5ns1Y`,
version 2). The operator approved the formatting, the bug fixes, and a
trimmed pulse briefing.

## What Changes

- Every outbound message (notifier classes, pulse briefing, probe watch,
  runtime upgrade job, CLI test alert) renders in one house layout:
  severity marker, plain-English headline that names the effect and the
  subnet, one meaning sentence, labelled key figures, provenance in an
  expandable details fold, and a final `Next:` line only when an action
  exists.
- Times render as Telegram `tg-time` entities (reader's timezone) with a
  UTC text fallback. Numbers use thousands separators, consistent units,
  and three significant figures for alpha prices.
- Subnets are named from the recorded panel snapshot name:
  `Subnet 49 (Nepher Robotics)` in alerts, `Nepher Robotics (49)` in the
  briefing.
- Links (GitHub compare and commit pages, taostats subnet pages) move into
  inline keyboard URL buttons. No LAN board button anywhere.
- Narrative-cluster alerts stop paging: the class tier moves to `shadow`
  (recorded and measured, sent nowhere). The operator does not want model
  adoption alerts (2026-10-04).
- Each pulse edition starts with its own header marker: ☀️ for the daily,
  🗓️ for the weekly.
- Probe-watch and upgrade-job reports move onto the shared HTML renderer
  and its plain-text fallback.
- `disable_web_page_preview` is replaced by `link_preview_options`.
- **BREAKING (briefing content)**: the pulse briefing drops total staked,
  subnet share, new accounts, ownership contested, the medium-verdict
  count, pushed-subnet count, repo re-points, the narrative section, the
  mining section, and the closing board link. The deregistration line
  becomes the top 3 non-immune subnets by prune rank, named. The code
  section names every high-impact incentive change and nothing else. Atlas
  health lines move into a details fold. A one-line rule-based summary
  leads each edition.
- Bug fixes:
  - a single-subnet chain-parameter change omits the subnet number;
  - glosses are inserted into headlines, commit subjects, and pallet labels;
  - repository alerts list duplicate commit subjects;
  - the briefing's deregistration line filters on `high` and drops every
    `critical` subnet;
  - briefing text is cut mid-word;
  - the briefing uses the banned `SN` form;
  - the briefing shows the bar as a fraction while alerts show a percentage;
  - the test alert contains an em dash.

Out of scope (shown in the review, not approved): silent sends, skipping
0-staged knowledge runs, a silent path for emission-off crossings,
outage recovery messages, and a registry section in the briefing. Each
class keeps its current paging behaviour. The 7 scrub-refused repository
alerts in the ledger are a separate investigation.

Assumption: the severity marker (🔴 🟠 🟢 🔵 ✅) is part of the layout the
operator approved, because every approved mockup shows it. It changes no
delivery behaviour.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `telegram-integration`: adds the house layout requirement; changes the
  HTML rendering, headline and gloss, repository breakdown, repo-versus-live,
  chain-parameter, and fleet-signal rendering requirements.
- `pulse-briefing`: adds the edition header marker; changes the section set, the section contents, the
  truncation order, and the closing line.

## Impact

- Code: `telegram/atlas_telegram.py` (renderer, transport, every
  adapter's builder), `telegram/atlas_briefing.py` (sections and packing),
  `livedata/atlas_probe.py` (`_drift_text`, cleared note),
  `upgrade/atlas_upgrade.py` (report texts), `telegram/config.json`
  (link templates, `narrative-cluster` tier to `shadow`).
- Docs: `telegram/docs/voice.md` (layout rules, subnet naming form),
  `telegram/README.md`.
- Tests: `telegram/tests/*`, `upgrade/tests/test_upgrade.py`,
  `livedata/tests` probe cases. The voice conformance tests change with
  the canon.
- `subnt/atlas_subnt.py` reuses `_Sources`, `_movers`, `_delta_pct`,
  `_table`, `stored_mining`, and `mining_top_delta`. Their signatures and
  behaviour stay unchanged.
- No store schema change, no new provider call, no model call.
