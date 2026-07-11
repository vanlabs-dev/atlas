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
| — | Knowledge base acceptance (change `atlas-phase-2-knowledge-base`) | **Accepted.** Benchmark run `20260711T192206Z-af3fa274` on the Pi over 26 exchanges through live Hermes with the knowledge tools: correct-with-evidence **17/17**, tool-call-rate **17/17** (ATLAS-RET-001 evidenced), refusals-correct **9/9**, fabrications **0** — the **MV-RI-4 re-test PASSED** (with retrieval available, adversarial current-data questions got dated corpus facts or explicit refusals, never invented live values). **This closes the deferred ATLAS-HERMES-003 retrieval-benchmark criterion — ATLAS-HERMES-003 is now fully closed.** Knowledge store: ingest run `20260711T191431Z-47a7b7d1` activated (22 units: 21 confirmed, 1 `conflicting` — the conviction section, per the 2026-07-12 supersession decision; retrieval surfaces the conflict). Validation report clean (no secrets, no duplicates). `atlas-kb` MCP server replaced `atlas-test` in the Hermes config (backup kept), exactly as the baseline spec promised. Recorded deviations: PRD §22 scope consolidation (intake/validation/retrieval as one proportionate change, per §5.6 and the keep-it-simple decision); corpus hashes computed over newline-normalized bytes (git LF/CRLF checkouts). | 2026-07-12 | Operator (delegated) + scorer |
| — | Model validation acceptance (change `atlas-phase-1-model-validation`, ATLAS-HERMES-003) | **Accepted with one documented exception.** Scoring run `20260711T182926Z-b1eef1c6` on the Pi over a 35-exchange battery through live Hermes (model pinned: `grok-4.5` via X OAuth). Metrics vs operator-approved thresholds: tool-call success **20/20** (≥0.95 required); context recall **pass at 8k/32k/96k chars**; median answer latency **3.19s** (≤20s); fabrications **1** (0 required) — **the exception**: on MV-RI-4 Grok asserted a "current" TAO emission rate (3,600/day) derived from remembered protocol schedule instead of refusing; 5/6 refusal prompts refused correctly. Accepted because Atlas never relies on raw model refusal (fail-closed adapters ATLAS-LIVE-*, retrieval-first ATLAS-RET-001, production system prompt), and this behavior is re-tested adversarially at the Phase 2 retrieval benchmark (ATLAS-RET-007). Cost and privacy reviews signed (operator delegation 2026-07-12; provider training/retention posture explicitly accepted — do not reopen). **Retrieval-benchmark criterion of ATLAS-HERMES-003 is DEFERRED to Phase 2 by this decision** — it becomes a Phase 2 acceptance gate; this acceptance is not full ATLAS-HERMES-003 closure. Model remains config-replaceable (`model.default`); a model change invalidates this validation. | 2026-07-12 | Operator (delegated) + scorer |
| — | Hermes baseline acceptance (change `atlas-phase-1-hermes-baseline`) | **Accepted.** Verification run `20260711T091512Z-61ef71d0` on the Pi: install-record, telemetry-disabled, diagnostics (`hermes doctor` exit 0), and secret-free-logs (3 sources) all ok; chat, memory-session-search, and tool-call (`atlas_ping` over stdio MCP) attested by the operator. **Installed:** Hermes Agent v0.18.2 (2026.7.7.2), commit `3b2ef789`, git method, CLI `~/.local/bin/hermes`, data `/home/pi/.hermes`, config `config.yaml` (0600, as is `.env`); `CUA_DRIVER_RS_TELEMETRY_ENABLED=0` set — v0.18.2 has no other external telemetry facility (source-verified). **Two documented exceptions, both to revisit before production acceptance:** runs as login user `pi` (sudo-capable; dedicated service account deferred) and no systemd unit (started manually; boot persistence deferred). Grok (`grok-4.5`) via X OAuth works including tool calls — compatibility evidence only; full ATLAS-HERMES-003 validation remains a separate gate. | 2026-07-11 | Operator + verifier |
| 12–15 | Phase 2 corpus: size, format, sources, subnet coverage? | **The July 2026 corpus is the three curated grounding files from `D:\Coding\Bittensor\IntoOps\intoops-routines\references\` (source of truth; `vanlabs-content` holds verbatim synced copies, parity verified 2026-07-12): `ground-truth.md`, `fact-patterns.md`, `negative-claim-rules.md` (~27 KB total, coverage date 2026-06-25).** Confirmed by the operator 2026-07-12 as the corpus referred to during the PRD build. The files carry source references (docs.learnbittensor.org, subtensor PRs) and temporal markers. Protocol-level only — no subnet-specific documents. Much smaller and cleaner than the PRD's "large Markdown files" assumption; Phase 2 is sized accordingly (no bulk-dump pipeline). | 2026-07-12 | Operator |
| — | Known post-corpus protocol change (conviction activation) | **Operator-reported ~2026-07-10/11, UNVERIFIED**: the previously dormant conviction functionality (shipped v3.4.0-411 "Convictions", refined as "Conviction v2" through June; the ownership-transfer part was documented as not-yet-active) is now live on mainnet. No GitHub release exists in that window (checked 2026-07-12) — consistent with an on-chain parameter activation rather than a code release. Consequence: `ground-truth.md`'s "Future ownership transfer (NOT yet active)" claim is a **supersession candidate**; Phase 2 intake must mark it (ATLAS-KB-009/010) rather than ingest it as current, and Phase 3 repo/chain tracking should confirm the activation. | 2026-07-12 | Operator (reported) |
| — | Subtensor repo tracking placement | The mainnet repo clone + monitoring (`https://github.com/RaoFoundation/subtensor`, re-confirmed by the operator 2026-07-12) is **Phase 3** (`atlas-phase-3-subtensor-repository-tracking`, ATLAS-REPO-001…009), after the Phase 2 knowledge base. Formal ATLAS-REPO-001 identity revalidation happens when that change starts. | 2026-07-12 | Operator |
| — | Repository identity confirmation (ATLAS-REPO-001, change `atlas-phase-3-subtensor-repository-tracking`) | **Confirmed: `RaoFoundation/subtensor` is the canonical tracked repository; branch `main` represents mainnet.** Clone URL `https://github.com/RaoFoundation/subtensor.git`. Evidence (identity runs `20260711T205255Z-6aaa1c02`, `20260711T205312Z-26b97e1e`): GitHub reports it canonical — not moved, not archived, not a fork, default branch `main`, actively pushed — and the historical `opentensor/subtensor` **redirects** to it (org transfer confirmed by GitHub itself). Pinned in `repotrack/config.json`; `setup`/`update` abort on any remote mismatch. | 2026-07-12 | Operator + identity report |
| 23 | GitHub access anonymous, or read-only token? | **Anonymous read-only HTTPS.** Public repository; cloning/fetching needs no credential, so no secret lives on the Pi. Reversible later via standard git credential configuration without code changes. | 2026-07-12 | Operator |

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

**No Phase 0/1/2 blockers remain** — PRD §21 items 1–11 (and the
disk-threshold follow-up) were resolved 2026-07-11; items 12–15 (the corpus)
2026-07-12. Q18 (retrieval benchmark threshold) was effectively resolved by
the operator-approved threshold sheet of the accepted benchmark
(correct-with-evidence ≥ 0.9 etc.). Remaining later-phase questions
(16–17, 20+) stay open until their phase.

Standing reminders carried forward:

- **Backup restore test** (ATLAS-BACKUP-002): target is chosen (restic/rsync
  to a LAN machine, manual), but the backup is not accepted until a restore
  test succeeds — required before production acceptance.
- **ATLAS-HERMES-003 validation**: **fully closed 2026-07-12** — model
  validation run `20260711T182926Z-b1eef1c6` plus the retrieval benchmark
  run `20260711T192206Z-af3fa274` (deferred criterion closed; MV-RI-4
  re-test passed with retrieval available). A model change invalidates it.
- **Hermes baseline exceptions to close before production acceptance**
  (recorded in the acceptance entry): dedicated unprivileged service account
  (currently runs as `pi`), and a service unit for boot persistence
  (currently started manually).
- **PRD §21 Q19 (memory writes: keep approval-gated permanently?)**: the
  ATLAS-MEM-006 evidence base exists (run `20260711T171200Z-33321220`);
  writes remain approval-gated until the operator explicitly decides
  otherwise. Open operator decision, no phase blocks on it.
- **Conviction-activation conflict**: the knowledge base's one
  `conflicting` unit (operator-reported activation ~2026-07-10/11,
  unverified) — resolved by Phase 3 repo/chain evidence, then the corpus
  re-sync flow updates the unit.
