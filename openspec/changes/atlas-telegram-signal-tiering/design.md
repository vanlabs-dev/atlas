# Design — atlas-telegram-signal-tiering

## Context

The outbound notifier (`telegram/atlas_telegram.py`) reads only
`meta.last_remote_sha` and emits `new head / detected`. `repotrack` already
records the full diff per range in `change_ranges` (commits, files, tags,
non-fast-forward, `_redact()`-ed machine summary). `livedata` already surfaces
the live runtime `spec_version` via the TaoStats chain-head adapter
(`_pp_chain_head_taostats`). The breakdown data therefore exists on-device; the
gap is (a) facts not read, (b) no significance policy, (c) no repo/chain
enrichment, (d) plain-text rendering.

## Goals / Non-Goals

**Goals:** tier repo alerts (significant vs churn); digest churn without silent
drop; concise breakdown on significant alerts; always distinguish repo vs live
chain; add a live `chain-runtime-upgrade` class; render with Telegram HTML +
safe escaping + 400 fallback.

**Non-Goals:** no change to inbound Hermes gateway; no new provider quota spend
(chain spec is read from what livedata already records); no investment/portfolio
classes; no wallet reachability; ledger schema unchanged.

## Decisions (settled during exploration)

- **Facts vs policy split.** `repotrack` records the *facts* (prev/new
  `spec_version` columns on `change_ranges`, computed via `git show
  <sha>:runtime/src/lib.rs` during `update`, since git access already lives
  there). The notifier owns *policy* (tiering, digest cadence, rendering). This
  keeps repotrack a recorder and the notification tuning where it belongs.
- **`sdk/` is churn.** SDK-only ranges trail spec bumps as regenerated bindings;
  they are a consequence, not a cause, so they do not warrant an immediate page.
- **Churn is digested, not dropped — and persisted before the watermark moves.**
  Because the repository-update watermark advances to the max `change_ranges.id`
  processed (churn included), a churn range that is only held "in memory" is lost
  on the next scan — it will never be re-read. So a churn range MUST be written to
  a durable pending-digest store *in the same step that advances the watermark
  past it*. The digest flush (on the next significant alert, or the periodic
  backstop) then drains that store. This is what actually makes "never dropped"
  true; the spec text alone does not guarantee it.
- **Watermark by `change_ranges.id`, with a one-time migration.** The class
  advances on the monotonic row id (as schema-drift already does). The *currently
  deployed* watermark value is a SHA string (`a9b329f…`), so first-run under the
  new code MUST translate that SHA to its `change_ranges.id` (or reseed to the
  current max id) rather than `int()`-ing a hex string and crashing / replaying
  the whole table. `init`/`seed_watermarks` must seed the id form.
- **Chain upgrade sourced from livedata, not a fresh call.** livedata persists
  the last-seen live `spec_version` and an upgrade event on change; the notifier
  reads that event store read-only. No extra TaoStats quota is spent by the
  notifier, and detection stays on validated data only.
- **Chain-upgrade timeliness is bounded by chain-head poll cadence.** livedata
  only records a spec change when `chain_head` is actually invoked, and today
  that is on-demand (when Hermes asks). Left as-is, a real 424→425 upgrade could
  go undetected for hours or until someone queries. So this change MUST add a
  lightweight scheduled `chain_head` read — piggybacked on the same hourly
  repo-update service the Telegram scan already rides — within the 2/min TaoStats
  self-cap. Without it, the chain-upgrade class exists but effectively never fires
  on time. This is the non-obvious operational dependency of the whole feature.
  Two implementation facts follow: `atlas_live.py` has **no CLI entry point
  today** (`chain_head` runs only inside `atlas_live_server.py` when Hermes
  asks), so the poll needs a minimal CLI subcommand; and its `ExecStartPost`
  line in `atlas-repotrack-update.service` must come *before* the Telegram scan
  line, so a fresh upgrade event is alerted in the same run, not an hour later.
- **Manifest path is config-driven, not hardcoded.** `spec_version` lives in
  `runtime/src/lib.rs` today, but the monorepo is moving trees; the read path is
  a config value, and an absent/renamed manifest records unknown (never guesses).
- **HTML via known-safe templates.** Only Bot-API-supported tags (`b`, `i`,
  `code`, `a`, `blockquote`, `blockquote expandable`, `tg-spoiler`). Escape
  `& < >` in every dynamic value. `blockquote expandable` holds the breakdown so
  the headline stays short.

## Significance classifier (churn is deny-by-default)

```
classify(range):
    if range.files_truncated or range.non_fast_forward:  return SIGNIFICANT  # fail-safe
    if spec_delta(range) != 0:                            return SIGNIFICANT  # strongest signal
    dirs = top_level_dirs(range.files)
    if dirs & PROTOCOL_DIRS:                              return SIGNIFICANT  # pallets/runtime/…
    if dirs and dirs ⊆ CHURN_DIRS:                        return CHURN        # provably low-signal
    return SIGNIFICANT   # unknown/new top-level dir → escalate, never silently churn
```

**Deny-by-default is the key correction:** churn is an *explicit allowlist*
(`.github/ docs/ website/ vendor/ sdk/`), and anything not provably in it —
including a top-level directory we have not seen before — escalates to
significant. The subtensor monorepo is actively reorganizing (the
`bittensor-core-exploration` consolidation moved whole trees), so a
complement-based "everything not protocol is churn" rule would silently drop a
new protocol area the first time it appears. Fail toward paging.

`spec_delta` comes from the new `change_ranges` columns (unknown → treated as 0
for the delta test only; directory rules still apply). `files_truncated` or
`non_fast_forward` short-circuit to significant because the recorded file list is
then known-incomplete and cannot be trusted to prove churn. Both directory sets
are config-driven so the operator can retune without code.

## Data flow

```
 repotrack.update()                    livedata (chain-head, validated)
   ├─ change_ranges (+prev_spec,         ├─ last_seen live spec_version
   │   +new_spec)                        └─ spec_upgrade event on change
   └─ (facts only, no policy)                     │
            │  read-only                          │ read-only
            ▼                                      ▼
 ┌───────────────────────── notifier scan ─────────────────────────┐
 │ repo adapter: ranges since change_ranges.id watermark           │
 │   → classify each → significant: render+send (with digest of    │
 │                       pending churn) → churn: accrue to digest   │
 │ chain adapter: new spec_upgrade events → high-priority render    │
 │ enrichment: read live spec for repo/chain delta line            │
 │ render → redact → HTML-escape → assert_sendable → send(HTML)     │
 │   on HTTP 400 → resend once as plain text, record fallback      │
 └──────────────────────────────────────────────────────────────────┘
```

## Message shapes (a replay of the 2026-07-12 evening, verified upstream)

The four heads classify as: range 1 `14bc6f9→647ca2b` spec 425→428
(significant), range 2 `→82142f9` `sdk/`-only (churn), range 3 `→ff1e1ed` spec
428→429 (significant), range 4 `→75798da` `.github/`-only (churn). Two
significant alerts, the second carrying the digest of range 2; range 4 stays
pending for the backstop flush.

```
Atlas · subtensor repo · runtime spec bump 425→428          (bold headline)
14bc6f90000 → 647ca2b0000 · 500+ commit(s) · 1200 file(s)
repo spec 428 · live Finney spec 424 · Δ+4 · not enacted on chain
source: repository (source code), not the live chain
▸ expandable quote, one fact per line:
    top areas: sdk (700) · pallets (300) · runtime (90)
    tags: v3.4.0
    • Merge pull request #2846 from RaoFoundation/bittensor-core-exploration
    • drand - round skip fix (#2794)
    from recorded change data · effects not verified
digested 1 low-signal update(s): sdk (82142f90000) · no protocol or spec
change                                                    (italic trailer)

Atlas · LIVE CHAIN UPGRADED · Finney runtime spec 424 → 425
the LIVE network changed (enacted), not the source repository
reference block: 8612004 · observed: <ts>
governance threshold 425 crossed · conviction-based subnet ownership
enforcement is now ENACTED
```

**Formatting rules (operator feedback 2026-07-13):** message bodies are
structured single-fact lines, never a prose blob — the breakdown is built
from the recorded fields (top areas, tags, bulleted subjects), not the
machine-summary sentence. Alert bodies NEVER contain em/en dashes: the
renderer normalizes them to `-` as a choke point, and composed strings use
`·` separators.

## Render / scrub / escape ordering

`build structured text → redact() → HTML-escape dynamic parts →
assert_sendable(final) → send(parse_mode=HTML)`. The scrubber runs on the final
rendered body so the HTML path inherits the "refuse if secret" guarantee. The
machine summary is already redacted in repotrack; escaping HTML entities does not
trip redaction.

**Size limit before rendering, never after.** `deliver_event` today slices the
body to `message_max_chars` (`text[:3500]`) — applied to a rendered HTML body
that slice can cut a tag or entity in half and 400 every oversized message. The
renderer MUST produce a body already within the limit with balanced tags
(shorten the breakdown content, not the markup); post-render truncation of HTML
is forbidden. The plain-text fallback sends the untagged structured text, not
the HTML source.

## Risks / trade-offs

- **HTML 400 = silent loss** (retry policy never-retries 400). Mitigation: the
  plain-text fallback resend, and rendering only from templated, escaped values.
- **`spec_version` field format drift** in `runtime/src/lib.rs`. Mitigation:
  record unknown rather than guess; a missing spec never fabricates a delta.
- **Cross-source read** (notifier → livedata.db) widens the notifier's read
  surface. It stays strictly read-only and degrades honestly when the live spec
  is unavailable (repo alert still sends, marked live-comparison-unavailable).
- **Digest timing:** if no significant alert arrives for a long stretch, churn
  could linger. Mitigation: a configurable periodic digest flush as a backstop.

## Open items for implementation

- Exact `change_ranges` column names / migration (additive; older rows carry
  unknown spec).
- livedata upgrade-event storage location (new table vs reuse of
  integration-health) and the last-seen watermark key.
- Digest flush cadence default (ride-next-significant only, or daily backstop).
- Pending-digest storage shape in the notifier (new table keyed by
  `change_ranges.id`) and its clear-on-delivery transaction.
- Message priority ordering when a scan yields both a chain-upgrade and repo
  alerts (chain-upgrade should surface first).
