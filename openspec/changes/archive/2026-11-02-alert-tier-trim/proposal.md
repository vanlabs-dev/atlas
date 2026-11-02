# Proposal

## Why

The pulse briefing has been off since 2026-10-19 (`aaa1f25`) because it was
too noisy. Four classes still sat at the `briefing` tier, so their events
were recorded as `briefed` and sent nowhere. In 14 days that was 50 econ-code
events, including 13 `high` verdicts, plus 12 registry renames and 4 knowledge
ingests (audit C1). The briefing has no registry section, so even with it on,
a deregistration would reach nobody (C2). Digest lines ignore their source
class's tier, so lines from the shadowed narrative-cluster class were sent
(C10). The operator chose to page only high-value events, then declined
econ alerts after the effectiveness read: at 7 days, 399 filled, the class
median is -2.702% against a -2.275% baseline.

## What Changes

- `econ-code` moves from `briefing` to `shadow`. Only a `high` verdict is
  emitted as `econ-code`; every other econ event (`med`, `unjudged`, no
  verdict) is emitted as the new delivery-only class `econ-code-minor`, also
  `shadow`. A later promotion of `econ-code` pages high verdicts only.
- `subnet-registry` pages registrations and deregistrations at `instant`.
  Renames are emitted as the new delivery-only class `subnet-rename` at the
  `shadow` tier.
- `knowledge-ingestion` and `gate-crossing-no-effect` move from `briefing` to
  `shadow`.
- `load_config` refuses a config in which any class is at the `briefing` tier
  while `briefing.enabled` is false.
- Each fleet digest line takes the tier of its source class, resolved from
  its dedup-key prefix. Only lines whose source class resolves to `instant`
  are kept for a digest. `signal-digest` is registered explicitly.

## Impact

- Code: `telegram/atlas_telegram.py`, `telegram/config.json`, telegram tests.
- Volume: in the 14 days to 2026-11-02 the new rules would have added no
  pages; no subnet registered or deregistered. The existing instant classes
  are unchanged (about 28 pages in the same window). The signal digest (11
  messages in that window) stops, because every current digest source is now
  shadowed.
- Rollback: set a class tier back in `telegram/config.json`.
