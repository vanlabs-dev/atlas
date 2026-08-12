# Proposal: telegram-voice-overhaul

## Why

Atlas's Telegram output — both inbound conversation and outbound alerts — is
mechanical and hard to parse: raw field dumps lead instead of meaning, jargon
is inconsistent across messages, and nothing states what an event means or
what (if anything) the operator should do. The operator has a proven voice
foundation (ADHD-mode layout + ASD-STE100 structure + Zinsser clarity) in
daily use elsewhere and wants Atlas to speak it — **without weakening the
accuracy contract**: every figure stays validated and sourced, and uncertainty
is stated plainly instead of hallucinated.

## What Changes

- Introduce a shared **voice foundation** (lexicon + layout + honesty rules)
  that both communication paths draw from: ADHD-mode layout (answer first, no
  framing, next action), ASD-STE100 structure for instructions (one action
  per sentence, imperative, warning-before-condition, approved lexicon),
  Zinsser clarity for prose. On conflict: STE wins instructions, Zinsser wins
  prose. No sentence-length caps — tight by discipline, not by limit.
- **Chat path:** replace the stock `SOUL.md` identity with the Atlas voice
  (core voice + "no tool evidence, no number" + fixed uncertainty phrasing)
  and add a `platform_hints.telegram` append for Telegram-specifics (mobile
  chunking, MEDIA tags, no tables).
- **Alerts path:** restructure all seven notification classes in
  `telegram/atlas_telegram.py` to verdict-led layouts (plain-language
  headline → sourced fact lines → next-action line), dropping jargon from
  prose while keeping every figure sourced, escaped, scrubbed, and
  de-duplicated exactly as today.
- Define a fixed **uncertainty vocabulary** (`confirmed` / `dated` /
  `not verified`) used identically in chat and alerts.
- Validation: lexicon-conformance unit tests on rendered alerts; the MV-RI-4
  adversarial battery re-run against the re-voiced chat to prove honesty held.

## Capabilities

### New Capabilities

- `agent-voice`: the shared voice foundation — approved lexicon, layout and
  prose rules, uncertainty vocabulary, and the honesty contract (no
  unvalidated numbers, explicit "I do not know") — applied to the Hermes
  system prompt (SOUL.md + Telegram platform hint) and to alert rendering.

### Modified Capabilities

- `telegram-integration`: the message-structure requirements change.
  Notifications remain safe Telegram HTML, scrubbed, size-bounded,
  de-duplicated, and single-fact at the fact-line level, but each class gains
  a verdict-led headline, plain-language glossing of jargon, and a
  next-action line; the "no em/en dashes" and HTML/fallback/scrub/ledger
  guarantees are unchanged.

## Impact

- `telegram/atlas_telegram.py` — per-class renderers restructured; config
  wording maps extended with the lexicon.
- `telegram/config.json` — lexicon and per-class headline wording.
- `~/.hermes/SOUL.md` (device config, not repo code) — new identity/voice
  text, operator-applied.
- `~/.hermes/config.yaml` (device config) — `platform_hints.telegram` append,
  operator-applied.
- `telegram/tests/` — new lexicon/structure assertions; existing suite
  updated to the new layouts.
- `hermes/modelval/` — MV-RI-4 adversarial battery re-run on device.
- No new dependencies; no changes to event sources, watermarks, ledger,
  scrubbing, or scheduling.
