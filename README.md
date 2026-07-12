# Atlas

Self-hosted, single-user Bittensor knowledge and live-data agent built on Hermes,
running on a Raspberry Pi. Built methodically in gated phases via OpenSpec.

**This README is the orientation map. Authoritative sources it points to:**
[prd.md](prd.md) (full product requirements), [docs/decisions.md](docs/decisions.md)
(resolved/open decisions), `openspec/specs/` (accepted capability specs), and
`openspec/changes/archive/` (completed changes with their proposal/design/tasks).

## Current status (2026-07-12)

**Phases 0–3 are complete and accepted on the device.** Hermes Agent
v0.18.2 runs on the Pi (Grok via X OAuth, validated), answering Bittensor
questions from the validated local knowledge base (`atlas-kb`) and from
the tracked subtensor repository clone (`atlas-repo`) — source-bound,
dated, commit-cited, fail-closed.

| Capability (accepted spec) | State |
|---|---|
| `device-inventory` | Done — read-only Pi inventory tool + clean baseline captured |
| `hardening-assessment` | Done — read-only posture assessor (11 ATLAS-ENV-003 areas) |
| `hardening-apply` | Done — 6 approved items applied + verified on the Pi |
| `hermes-baseline` | Done — manual install verified; acceptance run `20260711T091512Z-61ef71d0` |
| `memory-session-recall` | Done — ATLAS-MEM-001…006 verified on the Pi; acceptance run `20260711T171200Z-33321220` (approval gating on, all seven ATLAS-MEM-006 items attested) |
| `model-validation` | Done — ATLAS-HERMES-003 validated on the Pi; run `20260711T182926Z-b1eef1c6` (tool calls 20/20, context to 96k chars, 3.19s median latency; one documented refusal exception; retrieval criterion closed by the Phase 2 benchmark) |
| `knowledge-base` | Done — 22 units active (1 marked conflicting: conviction), `atlas-kb` tools live in Hermes; benchmark run `20260711T192206Z-af3fa274` perfect (17/17 grounded, 9/9 refusals, 0 fabrications — MV-RI-4 re-test passed) |
| `subtensor-repo-tracking` | Done — identity-validated full clone of `RaoFoundation/subtensor` on the Pi (non-shallow, push disabled, @ `14bc6f9f964b`), safe journaled updates, 581-file FTS index, `atlas-repo` tools live in Hermes (commit-and-file-cited answers; honest stale/no-evidence); conviction-activation conflict resolved at source level (PR #2800, spec 425) |

Latest closed-loop assessment `20260711T073125Z-d52a70e9`: **ok=7, finding=0**.
Hermes baseline carries 2 documented exceptions (runs as `pi`; no service
unit) — both to close before production acceptance.

## The device

- **Hardware/OS:** Raspberry Pi 5 Model B Rev 1.1, 16 GB RAM, 256 GB NVMe,
  Debian 13 (trixie), kernel 6.18, Python 3.13.
- **Access:** `ssh pi@192.168.0.150` — **key auth only** (password auth is
  disabled as of the hardening). A new session's key must be in the Pi's
  `~/.ssh/authorized_keys` to connect.
- **sudo needs a password** (no passwordless sudo). Automation must never enter
  it: privileged steps are run by the operator, or by tooling only when
  `sudo -n` already succeeds from a cached session. Never put a password on a
  command line.
- **Repo on the Pi:** cloned at `~/atlas`, kept current with `git pull`
  (remote: `github.com/vanlabs-dev/atlas`). This is the live working tree.
- **Applied hardening:** SSH key-only + X11Forwarding off; rpcbind and avahi
  disabled; nftables default-deny inbound (SSH allowed), enabled at boot;
  unattended security updates on (no auto-reboot).
- **Hermes on the Pi:** runs as user `pi`, started manually (no service unit
  yet). CLI `~/.local/bin/hermes`, data/config in `~/.hermes/`, code clone at
  `~/.hermes/hermes-agent`, model Grok (`grok-4.5`) via X OAuth — validated
  per ATLAS-HERMES-003. Memory and skill writes are **approval-gated**
  (`memory.write_approval` / `skills.write_approval: on`). The production
  knowledge tools are registered as stdio MCP server **`atlas-kb`**
  (`knowledge/atlas_kb_server.py`; it replaced the baseline `atlas-test`
  test tool on 2026-07-12), joined by **`atlas-repo`**
  (`repotrack/atlas_repo_server.py`, registered 2026-07-12) for
  repository evidence. Knowledge store + reports live in gitignored
  `var/knowledge/`, the subtensor clone + repo index in gitignored
  `var/repotrack/` on the Pi. Install record:
  `var/hermes/install-record.json` (on the Pi only). Full facts in the
  acceptance entries in [docs/decisions.md](docs/decisions.md).

## Repo layout

```
prd.md                     # governing product requirements (source of truth)
docs/decisions.md          # resolved + open decisions (check before re-asking)
inventory/                 # device-inventory tool (read-only), tests, schema, docs
hardening/                 # hardening-assessment tool (read-only)
hardening/apply/           # hardening-apply scripts (the ONLY device-mutating code)
hermes/                    # Hermes baseline verifier (read-only) + MCP test tool
hermes/memory/             # memory/session-recall verifier + scripted procedure (read-only)
hermes/modelval/           # ATLAS-HERMES-003 battery, runner, and read-only scorer
knowledge/                 # Phase 2 knowledge base: corpus snapshot, store, MCP tools, benchmark
repotrack/                 # Phase 3 subtensor repo tracking: clone/update/index CLI + MCP tools
openspec/specs/            # accepted capability specs
openspec/changes/          # active changes + archive/
var/                        # gitignored: device-sensitive inventory/assessment outputs
```

## Working conventions

- **OpenSpec workflow:** propose (`/opsx:propose`) → apply (`/opsx:apply`) →
  archive (`/opsx:archive`). One change per narrowly-scoped capability; see
  PRD §22 for the recommended sequence.
- **Read-only vs mutating:** `inventory/`, `hardening/` (except
  `hardening/apply/`), and `hermes/` never change the device. `hardening/apply/`
  is the only code that mutates, and only applies operator-approved items.
- **Fail closed / no assumptions:** tools report explicit unknowns
  (`permission-denied`, `unsupported-on-device`) rather than guessing.
- **Secrets never enter the repo, logs, or chat.** Outputs are redacted and
  written 0600 into gitignored `var/`.
- **Privileged assessment:** reading the firewall and `/etc/ssl/private` needs
  root, so full hardening acceptance runs the inventory + assessor under `sudo`
  (produces root-owned outputs). See [docs/decisions.md](docs/decisions.md)
  "Operational notes".
- **Tests run off-device;** WSL is used as a throwaway Linux environment for
  integration runs. The Pi itself is the acceptance environment.

## Next step

Phases 0–3 are complete: Atlas answers Bittensor questions from validated
local knowledge and cites subtensor source with commit and file references
through Hermes. Per PRD §22, next is **Phase 4**: live data, **TaoSwap
first** (keyless, contract confirmed 2026-07-12), then TaoStats where it
adds data (Q24–30 all decided 2026-07-12 — see the decision log; the
TaoStats key still needs installing per `env.example`). Q20 is decided
(hourly): repo-update timer files in `repotrack/systemd/` await the
operator's sudo install. Also open: the corpus re-sync to update the
conviction `conflicting` unit now that repo evidence is recorded, and the
standing debts before production acceptance from
[docs/decisions.md](docs/decisions.md): backup restore test, dedicated
service account, service unit for boot persistence, and the PRD §21 Q19
gating decision (evidence recorded; default stays approval-gated).
