# Atlas decision log

Resolved decisions from [prd.md](../prd.md) §21. Each entry: what was decided,
when, and by whom. Unlisted questions remain **open** — see the PRD for the
full list. Per PRD §5.5, nothing here may be assumed before it is recorded.

## Resolved

| # | PRD §21 question | Decision | Date | Decided by |
|---|---|---|---|---|
| 3 | Is anything on the Pi required to be preserved? | No — the operator formatted the Pi; nothing pre-existing remains. | 2026-07-11 | Operator |
| 4 | Clean OS reinstall permitted, or only in-place cleanup? | Clean reinstall — already performed. The Pi is a fresh OS install. | 2026-07-11 | Operator |
| 5 | How is the Pi accessed? | SSH, as user `pi`. | 2026-07-11 | Operator |
| — | Code transfer to the Pi (change `atlas-phase-0-device-inventory`, design D1a) | Git: this repo has a remote (`github.com/vanlabs-dev/atlas`) and is cloned on the Pi; `git pull` transfers code. Paste-over-SSH remains a fallback. | 2026-07-11 | Operator |

## Consequences already applied

- The formatted Pi means the ATLAS-ENV-002 removal plan is expected to be
  empty or trivial; the first inventory run now documents the *clean baseline*
  rather than a stale system. ATLAS-ENV-003 (hardening assessment) still
  applies in full to the fresh install.
- `var/` is gitignored: the Pi's checkout is the live working tree, and
  inventory reports (device-sensitive) must never be committed.

## Still open (blocking Phase 0/1 — from PRD §21)

1. Pi model — the inventory run will answer this; record it here.
2. OS, version, kernel — same, from the inventory report.
6. LAN/local only, or remote access required?
7. Acceptable LLM provider and model candidates.
8. Monthly LLM budget and latency tolerance.
9. May conversations leave the Pi to a hosted model?
10. External backup target.
11. Acceptable telemetry settings for Hermes and OpenSpec.
