# Tasks — atlas-telegram-signal-tiering

## 1. repotrack: record runtime spec_version facts

- [x] 1.1 Add additive `prev_spec` / `new_spec` columns to `change_ranges`
  (nullable; existing rows remain unknown).
- [x] 1.2 In `update()` / `_collect_range()`, read `spec_version` via `git show
  <sha>:<config manifest path>` (default `runtime/src/lib.rs`, not hardcoded —
  the monorepo moves trees) for prev and new heads; record unknown when the
  manifest or field is absent (never guess).
- [x] 1.3 Surface the spec delta through the existing repo status/change MCP
  tools so on-device queries see it too.
- [x] 1.4 Unit tests: spec bump recorded; manifest-absent → unknown; malformed
  field → unknown, update still succeeds.

## 2. livedata: persist live spec + upgrade event

- [x] 2.1 Persist last-seen live `spec_version` (value, reference block,
  observed-at) from validated chain-head responses only.
- [x] 2.2 Write a durable upgrade event on a changed `spec_version`; idempotent
  across restarts (no re-emit for an already-recorded value).
- [x] 2.3 Never record an upgrade from a failed or unvalidated response.
- [x] 2.4 Add a scheduled `chain_head` read within the 2/min TaoStats self-cap,
  so live spec changes are detected promptly rather than only when Hermes
  happens to query (without this the chain-upgrade class never fires on time).
  This needs two concrete pieces: a minimal CLI entry point in
  `livedata/atlas_live.py` (the module has none today — `chain_head` runs only
  via the MCP server), and an `ExecStartPost` line in
  `repotrack/systemd/atlas-repotrack-update.service` placed *before* the
  Telegram scan line so the same run alerts on a fresh upgrade event.
- [x] 2.5 Unit tests: change → one event; same value → none; restart → no
  re-emit; failed/invalid response → no record.

## 3. notifier: significance classifier + churn digest

- [x] 3.1 Rewrite the repository-update adapter to read `change_ranges` since a
  `change_ranges.id` watermark (replace the single-SHA watermark). Handle the
  one-time migration of the deployed SHA-valued watermark → its `change_ranges.id`
  (or reseed to current max id); never `int()` a hex SHA.
- [x] 3.2 Implement `classify(range)` deny-by-default: significant on spec delta,
  protocol dirs, files-truncated, or non-fast-forward; churn only when paths ⊆
  the configured churn allowlist (`.github/ docs/ website/ vendor/ sdk/`);
  unknown top-level dir → significant.
- [x] 3.3 Persist churn to durable pending-digest storage in the same step that
  advances the watermark past it; emit the digest on the next significant alert
  and clear only delivered ranges; add a configurable periodic flush backstop.
- [x] 3.4 Ensure churn never sends immediately, never drops, and survives across
  scans until digested (auditable pending storage).
- [x] 3.5 Unit tests over the four known heads (verified upstream 2026-07-13):
  heads 1 and 3 significant (647ca2b spec 425→428; ff1e1ed spec 428→429 touching
  pallets/runtime/common); heads 2 and 4 churn (82142f9 `sdk/`-only; 75798da
  `.github/`-only). Digest rides the next significant alert (the ff1e1ed alert
  digests 82142f9); churn survives an intervening scan; SHA→id watermark
  migration.

## 4. notifier: breakdown + repo/chain marking

- [x] 4.1 Build the significant-alert breakdown from the recorded machine summary
  + spec delta (reuse repotrack's `_redact()`-ed summary).
- [x] 4.2 Read the current live `spec_version` from `livedata.db` read-only;
  render the `repo spec N · live spec M · Δ · not enacted` line.
- [x] 4.3 Badge every repo alert as a source-code (repository) event; degrade
  honestly when the live spec is unavailable.
- [x] 4.4 Unit tests: both-clocks line present; live-unavailable path still sends
  and states the distinction.

## 5. notifier: chain-runtime-upgrade class

- [x] 5.1 Add a `chain-runtime-upgrade` adapter reading livedata upgrade events
  past its own watermark.
- [x] 5.2 Render as a high-priority live-chain (enacted) alert with prev→new live
  spec and reference block; surface the ≥ 425 governance threshold crossing.
- [x] 5.3 Register the class in `config.json` (enabled, source_db → livedata).
- [x] 5.4 Unit tests: upgrade event → one alert; threshold crossing noted;
  dedup/watermark correct.

## 6. notifier: Telegram HTML rendering

- [x] 6.1 Add `parse_mode=HTML` to `send_message`; introduce an HTML renderer
  limited to Bot-API-supported tags (`b`, `i`, `code`, `a`, `blockquote`,
  `blockquote expandable`, `tg-spoiler`).
- [x] 6.2 HTML-escape `& < >` in every dynamic value, ordered after `redact()`
  and before `assert_sendable()`. (Load-bearing: a real subtensor commit subject
  in-range contains `Vec<PerU16>`, which unescaped would 400 the send.)
- [x] 6.3 Render within `message_max_chars` with balanced tags (shorten content,
  not markup); remove/bypass the post-render `text[:max]` slice in
  `deliver_event` for HTML bodies — slicing rendered HTML cuts tags mid-entity
  and 400s every oversized message.
- [x] 6.4 On HTTP 400, resend the same event once as the untagged structured
  text (never the raw HTML source) and record the fallback in the ledger.
- [x] 6.5 Unit tests: dynamic values escaped; nesting valid; oversized breakdown
  stays within limit with balanced tags; simulated 400 → plain-text fallback
  recorded and delivered.

## 7. Config, docs, and verification

- [x] 7.1 Extend `telegram/config.json`: tier directory sets, digest cadence,
  `chain-runtime-upgrade` class, `parse_mode`.
- [x] 7.2 Update `telegram/docs/operator-setup.md`: tier semantics, digest
  cadence, repo-vs-chain marking, the new class, `init` note.
- [x] 7.3 Off-device end-to-end: fixture DBs reproduce the four heads + a live
  spec change; assert two significant alerts (the second carrying the digest of
  the `sdk/`-only churn), one chain upgrade, no churn pages, and the trailing
  `.github/`-only churn held pending for the backstop flush.
- [x] 7.4 Verify scrubber, ledger six-field record, and failure-isolation
  guarantees are unchanged (regression).
- [ ] 7.5 On-device acceptance: `init` (seed watermarks incl. new class), then a
  scan, confirming HTML render and repo/chain lines in a real Telegram message.
