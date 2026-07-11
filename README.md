# Atlas

Self-hosted, single-user Bittensor knowledge and live-data agent built on Hermes,
running on a Raspberry Pi. Built methodically in gated phases via OpenSpec.

**This README is the orientation map. Authoritative sources it points to:**
[prd.md](prd.md) (full product requirements), [docs/decisions.md](docs/decisions.md)
(resolved/open decisions), `openspec/specs/` (accepted capability specs), and
`openspec/changes/archive/` (completed changes with their proposal/design/tasks).

## Current status (2026-07-11)

Phase 0, the Phase 1 hardening, and the **Hermes baseline are complete and
accepted on the device**. Hermes Agent v0.18.2 runs on the Pi (Grok via
X OAuth), with the Atlas MCP test tool connected.

| Capability (accepted spec) | State |
|---|---|
| `device-inventory` | Done — read-only Pi inventory tool + clean baseline captured |
| `hardening-assessment` | Done — read-only posture assessor (11 ATLAS-ENV-003 areas) |
| `hardening-apply` | Done — 6 approved items applied + verified on the Pi |
| `hermes-baseline` | Done — manual install verified; acceptance run `20260711T091512Z-61ef71d0` |

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
  `~/.hermes/hermes-agent`, model Grok via X OAuth. MCP test tool registered
  as stdio server `atlas-test`. Install record: `var/hermes/install-record.json`
  (on the Pi only). Full facts in the acceptance entry in
  [docs/decisions.md](docs/decisions.md).

## Repo layout

```
prd.md                     # governing product requirements (source of truth)
docs/decisions.md          # resolved + open decisions (check before re-asking)
inventory/                 # device-inventory tool (read-only), tests, schema, docs
hardening/                 # hardening-assessment tool (read-only)
hardening/apply/           # hardening-apply scripts (the ONLY device-mutating code)
hermes/                    # Hermes baseline verifier (read-only) + MCP test tool
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

Per PRD §22, the next changes are the Phase 1 memory/recall verification
(ATLAS-MEM-*) and then ATLAS-HERMES-003 model validation (Grok benchmark:
tool-calling reliability, context, cost, latency, Bittensor retrieval) before
any Phase 2 corpus work. Standing debts before production acceptance, from
[docs/decisions.md](docs/decisions.md): backup restore test, dedicated
service account, service unit for boot persistence.
