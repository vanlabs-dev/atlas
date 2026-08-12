# Tasks: telegram-voice-overhaul

## 1. Voice canon

- [x] 1.1 Author `telegram/docs/voice.md`: approved lexicon (concept → one word), jargon-gloss map, ADHD layout rules, STE instruction structure (no length caps), Zinsser prose rules, uncertainty vocabulary (`confirmed` / `dated` / `not verified` in chat; source labels + `dated` / `n/a` markers in alerts), the honesty contract (no tool evidence → no number; never present remembered values as live), the STE-wins-instructions / Zinsser-wins-prose conflict rule, and the named verifications (renderer tests for alerts, battery voice probes for chat)
- [x] 1.2 Include in `voice.md` the full canonical `SOUL.md` text and the exact `platform_hints.telegram` append block (mobile-voice rules only: verdict first on a small screen, short lines, chunk-aware structure; the stock hint already covers Markdown, media tags, chunking)

## 2. Alert rendering (atlas_telegram.py + config)

- [x] 2.1 Add the lexicon and jargon-gloss maps to `telegram/config.json` following the `area_map` / `pallet_map` / `governs` precedent; maps are REQUIRED — a missing or incomplete map fails closed (render refuses), no code defaults
- [x] 2.2 Extend the existing render frame (`render_html` / `render_plain`): add the gloss-once helper and the shrink-order protection (expandable shrinks first, body lines drop next, next-action drops last, headline never dropped)
- [x] 2.3 Re-voice chain-runtime-upgrade: verdict headline, glossed jargon, fact lines unchanged, conditional next-action
- [x] 2.4 Re-voice chain-parameter-change (same shape as 2.3)
- [x] 2.5 Re-voice gate-crossing (same shape; suppressed events stay recorded-not-delivered)
- [x] 2.6 Re-voice fleet-signal (same shape)
- [x] 2.7 Re-voice repository-update (same shape; breakdown content rules untouched)
- [x] 2.8 Re-voice schema-drift (same shape)
- [x] 2.9 Re-voice knowledge-ingestion (same shape)
- [x] 2.10 Verify ledger, watermarks, dedup keys, cooldowns, and digest behavior byte-identical; no schema changes

## 3. Tests

- [x] 3.1 Lexicon conformance: stdlib test parses the `voice.md` lexicon table and asserts every `config.json` lexicon/gloss entry exists in canon; plus rendered-output assertions per class (approved words present, banned synonyms absent, gloss on first use only)
- [x] 3.2 Structure assertions per class: headline first, facts sourced, next-action present only when a real action exists (boilerplate `nothing` absent), worst-case fixtures within the size budget with balanced tags
- [x] 3.3 Shrink-order tests: oversized bodies shrink expandable first, drop body lines before the next-action line, never drop the headline
- [x] 3.4 Full telegram suite green off-device

## 4. Device application (operator steps)

- [x] 4.1 `git pull` on the Pi; run the telegram suite on-device
- [x] 4.2 Back up `~/.hermes/SOUL.md` and `~/.hermes/config.yaml` (repo backup naming convention), apply the canonical SOUL.md and the `platform_hints.telegram` append, restart `hermes-gateway` (user unit), then reset the Telegram session (the cached system prompt in the long-lived session would otherwise keep the old voice until a compression rebuild)
- [x] 4.3 Read-only verify the applied SOUL.md and platform hint match `voice.md` canon
- [x] 4.4 Deliver one `test --class` alert per class; confirm the new layout arrives and each delivery is ledger-recorded

## 5. Acceptance

- [ ] 5.1 Re-run the MV-RI-4 adversarial battery (`hermes/modelval`) against the re-voiced live chat, extended with 2–3 voice probes (answer-first structure, banned-synonym absence, next-action presence): dated corpus facts or explicit refusals, zero invented live values, voice probes pass
- [ ] 5.2 Record the acceptance in `docs/decisions.md` and update the README status line for `telegram-integration`
- [ ] 5.3 Schedule a dated calibration read ~1 week post-deploy (voice quality on real alerts + chat; findings become a follow-up change, not an archival blocker)
