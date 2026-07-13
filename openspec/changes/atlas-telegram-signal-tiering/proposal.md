## Why

The outbound repository-update alert is blind and un-triaged: it reads a single
value (`meta.last_remote_sha`) and emits `new head: <sha> / detected: <ts>`,
even though `repotrack` already writes a full per-range diff (`change_ranges`:
commits, changed files, tags, machine summary) one table over. The result is
that low-signal churn (docs, CI plumbing) pages the operator identically to a
runtime `spec_version` bump, the message body says nothing about *what* changed,
and — most importantly — a source-repo advance is presented in a way that reads
as if the live chain moved. In one evening the operator received four repo pings;
two were single-area churn (an `sdk/`-only range and a `.github/`-only range) and
two were real runtime spec bumps (425→428 and 428→429), with nothing in the
alerts to tell them apart.

## What Changes

- **Tier repo alerts by significance.** Classify each tracked commit range from
  its changed-file top-directories plus a runtime `spec_version` delta:
  `significant` (spec bump, or `pallets/ runtime/ precompiles/ common/` touched)
  vs `churn` (only `.github/ docs/ website/ vendor/ sdk/`). `sdk/`-only ranges
  are churn (they trail spec bumps as regenerated bindings).
- **Digest churn instead of paging on it.** Churn ranges are never sent
  immediately and never silently dropped; they are coalesced into a low-priority
  digest line carried by the next significant alert (or a daily summary).
- **Concise breakdown on significant alerts.** Significant alerts carry the
  existing machine summary (commit count, top changed areas, key subjects, tags)
  and the `spec_version` delta — data already on the device.
- **Mark repo vs live chain explicitly.** Every repo alert badges itself as
  source-code (not live) and states both clocks: `repo spec N · live Finney spec
  M · Δ · not enacted`, reading the current live `spec_version` from `livedata`.
- **New live chain-upgrade alert class.** When the *live* runtime `spec_version`
  changes (from `livedata` chain-head), emit a high-priority
  `chain-runtime-upgrade` notification — the "the network changed" signal, of
  which the conviction-enactment watch (spec ≥ 425) is a special case.
- **Render with Telegram HTML.** Send notifications with `parse_mode=HTML`,
  using an expandable blockquote for the breakdown, with mandatory escaping of
  all dynamic values and a plain-text fallback on an HTTP 400.
- **Watermark by change-range id.** The repository-update class advances on the
  monotonic `change_ranges.id` (as schema-drift already does), replacing the
  single-SHA watermark so multiple ranges and non-fast-forwards coalesce cleanly.

No breaking changes to existing delivered classes; the ledger, scrubber,
credential resolution, and failure-isolation guarantees are unchanged.

## Capabilities

### New Capabilities

_None — all changes extend existing capabilities._

### Modified Capabilities

- `telegram-integration`: the supported-scope requirement gains a fourth
  (chain-runtime-upgrade) class; new requirements add significance tiering with a
  churn digest, explicit repo-vs-chain marking, and HTML rendering with safe
  escaping and fallback.
- `subtensor-repo-tracking`: the per-range change record additionally captures
  the runtime `spec_version` at the previous and new heads (a `git show`
  content read), so significance and the spec delta are recorded facts.
- `live-data`: a new requirement persists the last-seen live runtime
  `spec_version` and records an upgrade event when it changes, so the notifier
  can alert on live chain upgrades without polling the provider itself.

## Impact

- **Code:** `telegram/atlas_telegram.py` (repo adapter rewrite to read
  `change_ranges`, significance policy, digest coalescing, repo/chain enrichment,
  HTML renderer + escaping + 400 fallback, new `chain-runtime-upgrade` adapter);
  `telegram/config.json` (tier/digest policy, `chain-runtime-upgrade` class,
  `parse_mode`); `repotrack/atlas_repo.py` (record prev/new `spec_version` in
  `change_ranges`); `livedata/atlas_live.py` (persist live spec + upgrade event,
  plus a minimal CLI entry point for the scheduled chain-head poll — the module
  has none today; `chain_head` currently runs only when Hermes asks via the MCP
  server); `repotrack/systemd/atlas-repotrack-update.service` (add the
  chain-head poll `ExecStartPost` line, ordered before the Telegram scan line).
- **Data:** additive `change_ranges` columns (repotrack) and a live-spec
  watermark/event store (livedata); telegram ledger schema unchanged.
- **Contracts:** the outbound notifier now reads `livedata.db` read-only in
  addition to its own source DBs (in-pattern with existing read-only source
  opens). Facts live in `repotrack`/`livedata`; tier/digest/render policy lives
  in the notifier.
- **Docs:** `telegram/docs/operator-setup.md` (tier semantics, digest cadence,
  the new class); live documentation sync at archive time.
