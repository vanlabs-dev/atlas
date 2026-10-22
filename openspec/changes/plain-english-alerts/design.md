# Design

## Context

See proposal.md for motivation. Observed state (2026-10-22, from the Pi):

- Every builder in `telegram/atlas_telegram.py` makes a `Message` and
  calls `message_event`, which renders `html` and `text` immediately and
  returns an event dict. `notify_scan` resolves the tier per event, then
  calls `deliver_event` (dedup, scrub, send, ledger). Events carry no
  `Message`, only the rendered strings.
- `Message` already has `to_dict` and `from_dict`.
- `fleet/atlas_econ_judge.py` is the working pattern for a Hermes one-shot:
  `hermes -z <prompt> -t <toolset>`, injectable runner, fenced untrusted
  input, fixed JSON shape, content-hash cache, fail soft.
- The ledger stores no message bodies. `events.final_failure` holds a
  free-text note.
- `telegram/config.json` already carries per-class `tier`, a `display` map
  for block-count settings, and a lexicon and gloss map held by a
  conformance test against `telegram/docs/voice.md`.
- The CoinGecko alert says `$.bittensor: missing required 'last_updated_at'`.
  `livedata/atlas_live.py:791` reads `entry["last_updated_at"]`, which
  CoinGecko only returns when asked for it.

## Goals / Non-Goals

**Goals:**

- Alerts a non-specialist reads in five seconds, with no loss of fact.
- A model that can change words only, enforced by code.
- Total fallback to templates, so a model outage costs wording and nothing else.

**Non-Goals:**

- No change to which events are detected, to cooldowns, eligibility, or
  to the effectiveness ledger.
- No rewrite of briefing or shadow events, the pulse (editions are off),
  or digests.
- No new credential, provider, or model id. No change to the chat voice.
- No briefing section for knowledge runs (not approved earlier, still not).

## Decisions

### 1. The rewrite sits between tier resolution and delivery

`message_event` gains a `message` entry (`msg.to_dict()`) on each event.
In `notify_scan`, after the tier resolves to `instant` and the ledger dedup
check passes, the hook calls `atlas_plain_rewrite.rewrite(event, config)`.
On success it rebuilds `html` and `text` from a `Message` whose headline,
meaning, up to two facts, body and `Next:` come from the rewrite. Severity,
details, buttons and source labels stay code-owned.

Alternative: rewrite inside each builder. Rejected: 10 builders, many call
sites, and briefing or shadow events would pay for a call they never send.

### 2. Rewrite module mirrors the econ judge

New `telegram/atlas_plain_rewrite.py`: `build_prompt`, `parse_reply`,
`check_reply`, `rewrite`, with an injectable runner. It calls Hermes with
`-z <prompt> -t <toolset>`; the toolset comes from `telegram/config.json`
`rewrite.toolset` and the rewrite stays off when it is empty, as the judge
does. Reply shape:

```json
{"headline": "...", "meaning": "...", "facts": [["Label", "value"]],
 "body": ["..."], "next": "... or null"}
```

### 3. Code converts, the model words

A converter runs before the prompt: 65,535-scale to percent
(`unit: "u16-fraction"` in the existing `display` map), blocks to days,
bar and shares already render as percentages. The prompt carries the
converted and raw values side by side plus the lexicon (`reward cutoff`,
`demand`, `version`) and a short rule list: one to three sentences, no
facts beyond the input, no advice beyond the input's own action, say what
it means for a holder or miner.

Alternative: let the model convert. Rejected: arithmetic errors would pass
the number check when the wrong value is also plausible.

### 4. The check is mechanical and strict

`check_reply` extracts numbers (with thousands separators, decimals, `%`),
dates, `Subnet N` ids and the event's subnet name from the reply. Each
number must appear in the set built from the input (raw, converted and
formatted forms; the integers 0 to 10 are always allowed as counts). Any
`Subnet N` with N different from the event's, a missing or altered subnet
name, a headline over 120 characters, a link, markup characters, an em dash,
or an over-budget body refuses the reply. A refusal is a fallback, not an
error. Strictness costs wording only, so false refusals are acceptable.

### 5. Fallback and bounds

Hermes call timeout 25 s (`rewrite.timeout_seconds`), one retry for non-zero
exit or unparseable reply, so at most about 100 s per event. A per-scan
budget `rewrite.scan_budget_seconds` (default 180) stops model calls once
spent and sends the rest from templates, so a Hermes outage cannot stall a
scan behind the hourly timer. Fallback reasons: `timeout`, `check-failed`,
`unparseable`, `hermes-error`, `budget`, `disabled`.

### 6. Cache and ledger

A `rewrite_cache` table in the notifier DB, keyed by `sha256(prompt version +
canonical input)`, stores the accepted reply. `events` gains a nullable
`rewrite` column (added with `ALTER TABLE` when absent) holding `used` or
`fallback:<reason>`. `status` aggregates the last 28 days.

### 7. Plain terms are a lexicon change, held by the existing test

`telegram/config.json` `voice.lexicon` and `telegram/docs/voice.md` section 2
change for alerts: the emission bar becomes `reward cutoff`, demand share
`demand`, runtime spec `version`. The conformance test continues to hold
config against canon. Technical terms stay in the fold. `SOUL.md` and the
chat path are untouched.

### 8. Behaviour changes are config-shaped

- `knowledge-ingestion`: `tier` to `briefing`. Rollback is one value. The
  briefing has no section for it, so the class goes quiet. Its template
  wording changes to "already in use, nothing to do" in case the tier is
  restored.
- No-effect crossings: `_gate_crossing_event` emits class
  `gate-crossing-no-effect` when `emission_enabled == 0`; the class is
  registered `delivery_only` at `briefing`. Cooldown and eligibility keys
  stay on `gate-crossing`. Task 3.2 checks that the new class neither reads
  nor writes the cooldown state.
- LLM-written `Next:`: allowed only for classes in
  `rewrite.next_allowed_classes` (initially `chain-parameter-change`) and
  only when the template has no `Next:` of its own. A code-written
  `Next:` is never replaced. The check refuses a `Next` that names a
  command or file path.

### 8a. The check refuses derived and rounded figures

Built and tested: a reply that rounds a figure (`0.834%` to `0.83%`) or
derives one (`6.25%` to "9 holdings instead of 16") is refused and the
template is sent. Hand-drafted examples on the review page did both, so
real replies will fall back more often than those examples suggest until
the prompt and the replay (task 2.7) show the rate. Allowing a derived
figure needs code to compute it and put it in the input.

### 9. CoinGecko repair

Found: CoinGecko returns `last_updated_at` for
`include_last_updated_at=true` and drops it for `True`, which is what
Python's urlencode sent. Fix: `query_string` in `livedata/atlas_live.py`
sends booleans in lowercase. The pinned schema stays. A regression test
holds the recorded reply (2026-10-22) against the schema.

## Risks / Trade-offs

- **Plausible wrong wording.** The check guards figures and names, not
  meaning. A fluent sentence can still mislead. Mitigation: the original
  stays in the fold, the prompt forbids advice beyond the input, and the
  first week of rewrites is read by the operator against `status` output.
- **Added latency.** One Hermes call per paged alert, a few seconds typical.
  The scan budget bounds the worst case. Page volume is about 1.5 a day.
- **Prompt injection through commit subjects or names.** Fenced as data,
  JSON-bound output, name and id check, no tools. Residual risk is wording
  only, never a tool action.
- **Voice drift between chat and alerts.** Alerts now say "reward cutoff"
  while chat says "bar". Accepted: the operator asked for simpler alerts.
  Chat can be aligned later.
- **Silent-by-tier knowledge.** If the upgrade job ever fails to activate a
  run, no alert says so. Mitigation: the upgrade job already pages on its own
  failure (`upgrade-*` classes).

## Open Questions

None that change what gets built. Assumed and recorded: timeout 25 s, scan
budget 180 s, `Next` rewrite limited to the `governs`-less parameter case.
