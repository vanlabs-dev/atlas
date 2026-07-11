# Proposal: atlas-phase-1-apply-hardening

Governing documents: [prd.md](../../../prd.md) (ATLAS-ENV-003, ATLAS-SEC-*), the operator-approved hardening plan (assessment run `20260711T065352Z-0190074a`, annotated plan on the Pi at `var/hardening/hardening-plan-20260711T065352Z-0190074a.md`), and the approval record in [docs/decisions.md](../../../docs/decisions.md).

## Why

The hardening assessment produced 6 findings, and the operator approved all 6 remediations on 2026-07-11. This is the project's **first device-mutating change**; everything before it was read-only. It must land before Hermes (Phase 1) so the agent is installed onto an already-hardened device. The critical risk is self-inflicted: SSH is the only management path, and two of the approved items (firewall, password-auth disable) can sever it if applied carelessly.

## What Changes

Applies exactly the 6 approved items — nothing more:

1. SSH key-only authentication (`PasswordAuthentication no`)
2. `X11Forwarding no`
3. Disable rpcbind (socket + service)
4. Disable avahi-daemon (socket + service)
5. Install nftables with default-deny inbound (allow loopback, established/related, SSH)
6. Install and enable unattended security updates

Delivery mechanism:

- One idempotent script per item under `hardening/apply/items/`, each with `check` (read-only state report), `apply`, `verify`, and `rollback` subcommands, plus a small shared library (audit logging, root/sudo detection, stop-on-failure conventions). No generic plan-execution engine — 6 one-off items on one device don't justify one (PRD §5.6).
- **Safe execution order** differs from plan numbering: low-risk items first (X11, rpcbind, avahi, unattended-upgrades), then the firewall (staged: syntax-check → non-persistent load → verify a *new* SSH session works → persist), and password-auth disable **last**, so every risky step retains a recovery path.
- Every action appends to an audit log (`var/hardening/apply-log.jsonl`).
- Acceptance is closed-loop: re-run the existing assessor after application; the three `finding` areas must flip to `ok`.
- Explicitly out of scope: backup configuration (Q10 deferred TBD), disk-threshold enforcement (working values only), any Hermes installation, and any hardening item not in the approved plan.

## Capabilities

### New Capabilities

- `hardening-apply`: Controlled application of operator-approved hardening plan items — one at a time, idempotent, verified per item and by full re-assessment, with lockout-prevention protocol, per-item rollback, and a complete audit trail. Applies only items carrying an approval record; never invents scope.

### Modified Capabilities

None. (`hardening-assessment` is reused as-is for post-apply verification; `device-inventory` unchanged.)

## Impact

- **Device**: real state changes on the Pi — sshd config, three services disabled/enabled, two packages installed, one firewall config created. Each is individually reversible; rollback commands are part of each script.
- **Access risk**: SSH lockout is possible if the protocol is violated; the design makes the protocol explicit (keep the active session, verify a second fresh connection after each risky step, physical console as last resort). Password auth is removed only after key-only access is re-verified.
- **Privilege**: items require root. Scripts run under `sudo` invoked by the operator (or by the agent only if passwordless sudo is available — no password is ever entered by the agent). Scripts never embed or prompt for credentials.
- **Testing**: off-device testing is dry-run/syntax/logic only — the dev machine and WSL environments are NOT mutated. The gated, one-item-at-a-time Pi execution *is* the acceptance run, per-item verified.
- **Downstream**: unblocks `atlas-phase-1-hermes-baseline` on a hardened device. The nftables default-deny posture means future services (health endpoint, frontend) need explicit rules — intended.
