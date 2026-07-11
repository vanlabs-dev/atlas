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
| 10 | External backup target? | **Restic/rsync to a LAN machine, run manually (not automated).** Supersedes the earlier deferral. Per ATLAS-BACKUP-002 the backup is not accepted until a restore test succeeds into an isolated location; that test must pass before production acceptance. | 2026-07-11 | Operator |
| — | Hardening apply acceptance (change `atlas-phase-1-apply-hardening`) | **All 6 items applied and verified on the Pi.** Independent checks: fresh key login works, password auth refused (`Permission denied (publickey)`), ports 111/5353 closed, nftables default-deny active and persistent. Closed-loop re-assessment `20260711T073125Z-d52a70e9`: ok=7, finding=0 (ssh/firewall/unattended-updates flipped to ok; remaining non-ok are the 2 deferred decisions + 2 future-phase items). | 2026-07-11 | Operator + assessment |
| 6 | LAN/local only, or remote access required? | **LAN-only for now.** Keep the nftables default-deny posture (SSH only). Telegram (Phase 5) is outbound-only and unaffected. Revisit remote access (e.g. Tailscale/WireGuard) when the frontend phase arrives. | 2026-07-11 | Operator |
| 7 | Acceptable LLM provider and model candidates? | **Grok (xAI) via X OAuth** (subscription auth, not a metered API key) is the first candidate. Subject to full ATLAS-HERMES-003 validation during the Hermes baseline — including whether Hermes supports Grok via OAuth at all; if not, fall back is an open question for the operator. Model must remain replaceable through configuration. | 2026-07-11 | Operator |
| 8 | Monthly LLM budget and latency? | **~$20/month, interactive latency** (a few seconds to first token; longer acceptable for tool-heavy answers). With Grok via X OAuth the subscription itself is expected to be the cost. | 2026-07-11 | Operator |
| 9 | May conversations leave the Pi to a hosted model? | **Yes — hosted models allowed.** Prompts and retrieved evidence may be sent to the provider. Secrets and wallet material are already excluded from conversations/memory by design (ATLAS-MEM-005, ATLAS-API-008). | 2026-07-11 | Operator |
| 11 | Telemetry settings for Hermes and OpenSpec? | **Disable all telemetry** (usage analytics and crash reporting) at install time. The only traffic leaving the Pi should be the LLM API itself. Verified as part of the ATLAS-HERMES-005 diagnostic baseline. | 2026-07-11 | Operator |
| 12 | Disk thresholds (assessor working values) | **Confirmed: 80% warn / 90% stop-nonessential.** These become the service-configuration values (ATLAS-BACKUP-005 context). Root fs is at 3% today. | 2026-07-11 | Operator |
| — | Hermes install mode (change `atlas-phase-1-hermes-baseline`) | **Operator runs the Hermes install and interactive setup manually on the Pi.** The repo change ships only a read-only post-install verification script covering the ATLAS-HERMES-005 baseline (service user, no general sudo, diagnostics, chat, tool discovery, memory/session search, restart, no secrets in logs). The ATLAS-HERMES-001 install record (source, version, date, update/rollback method, service user, data dir, config path) is captured by the operator and checked by the verifier where readable. | 2026-07-11 | Operator |
| — | Memory/session-recall acceptance (change `atlas-phase-1-memory-and-session-recall`) | **Accepted.** Verification run `20260711T171200Z-33321220` on the Pi: all 4 automated checks ok — install-record; approval-gating (`memory.write_approval` + `skills.write_approval` both on; found ABSENT on the device 2026-07-12, i.e. OFF by v0.18.2 default, and enabled by the operator before the procedure); memory-hygiene (secret- and canary-free, no bulk domain content); session-store (`state.db` FTS5 present, recall marker findable read-only). All seven ATLAS-MEM-006 items performed per `hermes/memory/docs/procedure.md` and attested by the operator: preference retention, correction replacement, stale removal (observed as true deletion, not tombstone), duplicate prevention, prior-session lookup, secret rejection, domain separation. Deviation noted and corrected mid-procedure: Hermes saved the recall marker as a *memory*; it was removed before the lookup test so session *search* was what passed, not memory recall. This run is the ATLAS-MEM-006 evidence base for PRD §21 Q19 — memory writes stay approval-gated until the operator decides otherwise. | 2026-07-12 | Operator + verifier |
| — | Hermes baseline acceptance (change `atlas-phase-1-hermes-baseline`) | **Accepted.** Verification run `20260711T091512Z-61ef71d0` on the Pi: install-record, telemetry-disabled, diagnostics (`hermes doctor` exit 0), and secret-free-logs (3 sources) all ok; chat, memory-session-search, and tool-call (`atlas_ping` over stdio MCP) attested by the operator. **Installed:** Hermes Agent v0.18.2 (2026.7.7.2), commit `3b2ef789`, git method, CLI `~/.local/bin/hermes`, data `/home/pi/.hermes`, config `config.yaml` (0600, as is `.env`); `CUA_DRIVER_RS_TELEMETRY_ENABLED=0` set — v0.18.2 has no other external telemetry facility (source-verified). **Two documented exceptions, both to revisit before production acceptance:** runs as login user `pi` (sudo-capable; dedicated service account deferred) and no systemd unit (started manually; boot persistence deferred). Grok (`grok-4.5`) via X OAuth works including tool calls — compatibility evidence only; full ATLAS-HERMES-003 validation remains a separate gate. | 2026-07-11 | Operator + verifier |

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

## Operational notes

- **Firewall/secret-file assessment needs a privileged inventory.** Reading the
  nftables ruleset and `/etc/ssl/private` requires root, so full hardening
  acceptance runs `sudo python3 inventory/atlas_inventory.py run` then
  `sudo python3 hardening/atlas_hardening.py assess`. These produce root-owned
  0600 outputs in `var/`; an unprivileged assessor cannot read a root-owned
  report (it fails closed rather than guessing). Routine, non-firewall checks
  remain fine unprivileged.

## Still open

**No Phase 0/1 blockers remain** — PRD §21 items 1–11 (and the disk-threshold
follow-up) are all resolved above as of 2026-07-11. Later-phase questions
(PRD §21 items 12+) stay open until their phase.

Standing reminders carried forward:

- **Backup restore test** (ATLAS-BACKUP-002): target is chosen (restic/rsync
  to a LAN machine, manual), but the backup is not accepted until a restore
  test succeeds — required before production acceptance.
- **ATLAS-HERMES-003 validation**: Grok via X OAuth is confirmed *working*
  (chat + tool calls, baseline acceptance 2026-07-11) but not *validated*:
  tool-calling reliability, context window, cost, latency, and the Bittensor
  retrieval benchmark must still pass before production use.
- **Hermes baseline exceptions to close before production acceptance**
  (recorded in the acceptance entry): dedicated unprivileged service account
  (currently runs as `pi`), and a service unit for boot persistence
  (currently started manually).
- **PRD §21 Q19 (memory writes: keep approval-gated permanently?)**: the
  ATLAS-MEM-006 evidence base now exists (acceptance run
  `20260711T171200Z-33321220`); writes remain approval-gated until the
  operator explicitly decides otherwise — a Phase 2 gate.
