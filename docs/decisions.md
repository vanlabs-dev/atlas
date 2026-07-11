# Atlas decision log

Resolved decisions from [prd.md](../prd.md) §21. Each entry: what was decided,
when, and by whom. Unlisted questions remain **open** — see the PRD for the
full list. Per PRD §5.5, nothing here may be assumed before it is recorded.

## Resolved

| # | PRD §21 question | Decision | Date | Decided by |
|---|---|---|---|---|
| 1 | What Raspberry Pi model is in use? | Raspberry Pi 5 Model B Rev 1.1, 16 GB RAM, 256 GB NVMe (root fs 3% used). Evidence: inventory run `20260711T062206Z-5be02d8f`. | 2026-07-11 | Inventory report |
| 2 | What OS, version, kernel? | Debian GNU/Linux 13 (trixie), kernel 6.18.34+rpt-rpi-2712, Python 3.13.5. Evidence: same run. | 2026-07-11 | Inventory report |
| 3 | Is anything on the Pi required to be preserved? | No — the operator formatted the Pi; nothing pre-existing remains. | 2026-07-11 | Operator |
| 4 | Clean OS reinstall permitted, or only in-place cleanup? | Clean reinstall — already performed. The Pi is a fresh OS install. | 2026-07-11 | Operator |
| 5 | How is the Pi accessed? | SSH, as user `pi`. | 2026-07-11 | Operator |
| — | Code transfer to the Pi (change `atlas-phase-0-device-inventory`, design D1a) | Git: this repo has a remote (`github.com/vanlabs-dev/atlas`) and is cloned on the Pi; `git pull` transfers code. Paste-over-SSH remains a fallback. | 2026-07-11 | Operator |
| — | Classification worksheet resolution (run `20260711T062206Z-5be02d8f`) | Fresh OS install — **preserve everything, nothing to remove**. All worksheet rows are stock Debian 13 components; no stale Atlas/Hermes/Bittensor material exists. The ATLAS-ENV-002 removal plan is therefore formally empty. | 2026-07-11 | Operator |
| — | Hardening plan approval (assessment run `20260711T065352Z-0190074a`) | **All 6 proposed items approved**: SSH key-only auth, X11Forwarding off, disable rpcbind, disable avahi/mDNS, nftables default-deny inbound (SSH allowed), unattended security updates. Annotated plan on the Pi at `var/hardening/hardening-plan-20260711T065352Z-0190074a.md`; application via `atlas-phase-1-apply-hardening`. | 2026-07-11 | Operator |
| 10 | External backup target? | **Explicitly deferred (TBD).** Must be resolved before production acceptance (ATLAS-BACKUP-002); does not block the approved hardening items. | 2026-07-11 | Operator |

## Consequences already applied

- The formatted Pi means the ATLAS-ENV-002 removal plan is expected to be
  empty or trivial; the first inventory run now documents the *clean baseline*
  rather than a stale system. ATLAS-ENV-003 (hardening assessment) still
  applies in full to the fresh install.
- `var/` is gitignored: the Pi's checkout is the live working tree, and
  inventory reports (device-sensitive) must never be committed.

## Observations queued for the hardening assessment (ATLAS-ENV-003)

From inventory run `20260711T062206Z-5be02d8f` (clean baseline, no judgement
applied yet): no firewall tooling installed (ufw/nft/iptables all absent);
sshd config leaves `PasswordAuthentication` at its default (yes — operator
plans key-only after rotation); `X11Forwarding yes`; rpcbind listening on
0.0.0.0:111; mDNS (avahi) active. No Hermes, containers, or user software
present.

## Still open (blocking Phase 0/1 — from PRD §21)

6. LAN/local only, or remote access required?
7. Acceptable LLM provider and model candidates.
8. Monthly LLM budget and latency tolerance.
9. May conversations leave the Pi to a hosted model?
10. External backup target — explicitly deferred TBD (see Resolved table);
    listed here as a reminder that it must precede production acceptance.
11. Acceptable telemetry settings for Hermes and OpenSpec.
12. Disk thresholds: assessor's 80% warn / 90% stop-nonessential stand as
    working values; confirm or adjust before they become service
    configuration (ATLAS-BACKUP-005).
