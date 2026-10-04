# Design

## Context

See `proposal.md` for the motivation. Current state that shapes the build:

- `telegram/atlas_telegram.py` composes every class through
  `render_html` / `render_plain(headline, lines, expandable, trailer,
  next_action, glosses)`. Inline sentinels (`\x01`..`\x04`) mark code and
  bold spans. `_gloss_message` glosses across the headline, the body lines,
  and the expandable text, which is how glosses reach recorded data.
- `send_message` posts a form-encoded `sendMessage` with
  `disable_web_page_preview` and no `reply_markup`.
- `livedata/atlas_probe.py` and `upgrade/atlas_upgrade.py` send plain
  text through `atlas_probe.telegram_send`, outside the delivery ledger.
- `telegram/atlas_briefing.py` builds six sections of strings. Its packer
  adds bold section names and a closing line. `subnt/atlas_subnt.py`
  imports `_Sources`, `_movers`, `_delta_pct`, `_table`, `stored_mining`,
  and `mining_top_delta` from it.
- Names live in `panel_snapshot.name`. The dereg rank is in
  `dereg_prune_rank`, immunity in `dereg_is_immune`.
- Tests assert many current strings, mainly `telegram/tests/test_voice.py`.

## Goals / Non-Goals

**Goals:**

- One message model and one renderer for every sender.
- Layout rules enforced by tests, not by each builder.
- Keep the stdlib-only, read-only, fail-closed posture.

**Non-Goals:**

- No change to tiers, cooldowns, dedup keys, watermarks, or ledger rows.
- No `disable_notification`, recovery messages, or registry section (not
  approved).
- No probe or upgrade ledger integration. That is a separate change.
- No paraphrasing of verdict text. The renderer clips `what_changed` on a
  word boundary. The short phrasings in the review mockup are illustrative.

## Decisions

### D1. A `Message` value replaces positional render arguments

Add a small dataclass in `atlas_telegram.py`:

```python
@dataclass
class Message:
    severity: str                  # "act" | "watch" | "good" | "info" | "done"
    headline: str
    meaning: Optional[str] = None  # one body sentence; glosses attach here only
    facts: List[Tuple[str, str]] = field(default_factory=list)  # (label, value)
    body: List[str] = field(default_factory=list)  # bullets or list lines
    details: List[str] = field(default_factory=list)  # provenance fold
    next_action: Optional[str] = None
    buttons: List[Tuple[str, str]] = field(default_factory=list)  # (text, url)
```

`render_html(msg, max_chars, glosses)` and `render_plain(...)` render it.
Every builder returns `{"event_id", "event_class", "created_at", "text",
"html", "buttons"}`.

Alternative considered: keep the old signature and add arguments. This was
rejected because the gloss leak comes from treating the headline and
recorded text as glossable prose. A typed model can gloss `meaning` alone.

Span markup stays as sentinels inside strings. A value from a store is
always passed through `rec(text)`, which strips sentinels, so recorded text
cannot open a tag.

### D2. Glossing is limited to `meaning` and composed body lines

`_gloss_message` runs over `meaning` and over `body` lines that the
builder flags as composed. Headlines, fact labels and values, details, and
recorded strings are never glossed. The voice tests move from "gloss on
first use anywhere" to "gloss on first use in prose, never in data".

### D3. Shrink order

The order is: details fold first (whole lines from the end, then a clipped
last line), then `body` lines from the end, then `facts` from the end, then
`meaning`. `next_action` and the headline are never dropped. This keeps the
current spec's guarantee and extends it to the new parts.

### D4. Time rendering

`fmt_time(iso, fmt="wDT")` parses the recorded ISO string and returns the
HTML `<tg-time unix="N" format="wDT">Fri 2 Oct, 19:02 UTC</tg-time>`, plus
the plain fallback `Fri 2 Oct, 19:02 UTC`. Relative times use `format="r"`.
A value that does not parse renders as recorded, marked `dated`. The entity
goes through a third sentinel pair so escaping stays a single pass.

### D5. Number helpers

The helpers live in one place, with unit tests:

- `fmt_int` gives `9,197,096`.
- `fmt_pct(fraction, digits)` gives `0.858%`.
- `fmt_tao(x)` gives three significant figures, `0.00425 τ`.
- `fmt_usd` gives `$292.23`.
- `fmt_change(pct)` gives `+12.6%` / `−51%`, using a minus sign rather than
  a hyphen in figures.
- `compact` is kept for line churn.

### D6. Subnet names

`subnet_names(live_conn) -> Dict[int, str]` reads the latest name per
netuid once per scan or edition. Two display helpers use it:
`subnet_label(n, names)` gives `Subnet 49 (Nepher Robotics)`, and
`subnet_tag(n, names)` gives `Nepher Robotics (49)`. A missing name, or the
literal `Unknown`, degrades to the number alone. The fleet adapter's
`_subnet_label` (owner/repo) is replaced by the panel name. The repo path
moves to the details fold.

### D7. Buttons and transport

`send_message` gains `buttons` and sends `reply_markup` as JSON
(`{"inline_keyboard": [[{"text", "url"}], ...]}`, two per row) and
`link_preview_options={"is_disabled": true}`. The plain-text fallback
resends with the same buttons. If Telegram rejects the markup (HTTP 400 on
the plain resend too), one last attempt without buttons runs and is
recorded in `final_failure`. URL templates go in `telegram/config.json`
under `links`:

```json
"links": {
  "subtensor_compare": "https://github.com/RaoFoundation/subtensor/compare/{prev}...{new}",
  "subtensor_releases": "https://github.com/RaoFoundation/subtensor/releases",
  "github_commit": "https://github.com/{repo}/commit/{sha}",
  "atlas_commit": "https://github.com/vanlabs-dev/atlas/commit/{sha}",
  "taostats_subnet": "https://taostats.io/subnets/{netuid}"
}
```

The fleet repo slug comes from `slots.github_repo`. A missing key or value
omits the button.

### D8. Severity selection is per class, in code

The table below is held in one function, `severity_for(event_class,
fields)`, with tests.

| Class / outcome | Marker |
|---|---|
| chain-runtime-upgrade | 🟠, or 🔴 when the governance spec is crossed |
| chain-parameter-change: bar params, `SubnetEmissionEnabled` | 🔴 |
| chain-parameter-change: other or undescribed | 🟠 |
| gate-crossing: rose | 🟢 |
| gate-crossing: fell | 🔴 |
| gate-crossing: emission disabled | 🔵 |
| fail-closed, probe drift, upgrade blocked | 🔴 |
| schema-drift, upgrade retrying or stalled, repo significant, econ, cluster, watchlist, knowledge with units staged | 🟠 |
| churn digest, signal digest, knowledge with 0 staged, upgrade waiting, subnet-registry | 🔵 |
| upgrade updated, upgrade dry run, probe cleared, test | ✅ |
| narrative-cluster | 🟠 (shadow tier: rendered for the ledger, never sent) |
| pulse daily / weekly | ☀️ / 🗓️ edition marker, not a severity marker |

### D9. Probe and upgrade senders

`atlas_probe.telegram_send(text)` becomes `telegram_send(msg: Message)`.
It renders HTML and plain text, scrubs both, sends HTML, and falls back on
400. `_drift_text` becomes `drift_message(result)` and returns a `Message`.
The cleared note becomes a ✅ `Message`. `atlas_upgrade.Job.report(state,
kind, msg)` stores the rendered plain text and HTML in `pending_report`, so
a retried report is identical. Its dedup key is unchanged. The full Claude
summary goes in the details fold, bounded by the shrink path rather than
the current 1,200-character tail.

### D10. Briefing composition

Sections return `List[str]` as they do today. A new set replaces the old
one:

- `network`
- `rules`
- `price_moves`
- `share_moves`
- `watch`
- `high_impact`
- `health`, rendered in the fold

`_summary_line(figures)` builds the lead from figures already in the
edition. The packer emits `Message`-style HTML with bold section names, the
fold last, and no board link. Drop order: health fold, high_impact overflow
(weekly), share_moves, price_moves, watch, rules. The network section is
never dropped.

Kept for subnt with identical behaviour: `_Sources`, `_movers`,
`_delta_pct`, `_table`, `stored_mining`, `mining_top_delta`, and
`MINING_MODEL_UNRECORDED`. Only the briefing stops calling the mining
helpers. `_mining_section` and `_narrative_section` are deleted, and
`compose` no longer derives the mining next-action.

The dereg query:

```sql
SELECT netuid, name FROM panel_snapshot
WHERE id IN (SELECT MAX(id) FROM panel_snapshot GROUP BY netuid)
  AND dereg_prune_rank IS NOT NULL AND dereg_is_immune = 0
ORDER BY dereg_prune_rank ASC LIMIT 3
```

`dereg_is_immune IS NULL` is excluded. An unknown immunity is not shown as
at risk.

Rule-change merging: rows of one item and netuid in the window collapse to
one line. If the last value equals the first previous value, the line reads
"set, then reset to X". Otherwise it reads "X → Y".

### D11. Price at a crossing

The gate-crossing builder reads `moving_price_tao` from `panel_snapshot`
at the event's `block_number`, falling back to the latest row at or below
it. If none exists, the price line is omitted. This is a read of a recorded
row, so the "renderers do not infer" rule holds.

## Risks / Trade-offs

- [`tg-time` unsupported on an old client] → The entity carries UTC text,
  which older clients show as is.
- [Emoji render as tofu on some desktops] → They are the first character
  only, and the headline text stands alone.
- [Large test rewrite hides a regression] → Write golden-file fixtures per
  class from the 2026-10-04 Pi samples first, assert structure (marker,
  headline, fold, last line) rather than full strings, and keep every
  behavioural test (tiers, dedup, cooldown, watermarks) untouched.
- [`reply_markup` rejected for a malformed URL] → URLs are built from
  templates plus escaped recorded values, then validated with
  `urllib.parse`. The last resend without buttons protects delivery.
- [subnt depends on briefing internals] → `subnt/tests` runs in the gate.
  The shared helpers stay unchanged.
- [Verdict clipping reads worse than the mockup's paraphrase] → This is
  accepted. Paraphrasing would need a model call, which the briefing spec
  forbids.

## Migration Plan

1. Land on `main` from the workstation. The Pi picks it up by `git pull`
   in its repo checkout. No store migration, no config secret, and no unit
   change are needed.
2. Run the Pi check before the next scan:
   `python3 telegram/atlas_telegram.py test --class schema-drift`.
3. Rollback: revert the commit. Ledger rows and watermarks are untouched,
   so nothing replays.

## Open Questions

- Should the probe and upgrade sends join the delivery ledger? Deferred to
  its own change; it does not affect rendering.
