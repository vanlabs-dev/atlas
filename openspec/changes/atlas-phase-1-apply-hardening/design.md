# Design: atlas-phase-1-apply-hardening

## Context

First mutating change. Input: the operator-approved plan from assessment run `20260711T065352Z-0190074a` (all 6 items approved 2026-07-11; backup Q10 explicitly deferred). Device: Pi 5, fresh Debian 13, user `pi` over SSH (key auth already working — the agent connects with `ssh -o BatchMode=yes`), repo checkout at `~/atlas`. SSH is the only management path; the operator has physical console access as the recovery of last resort.

## Goals / Non-Goals

**Goals:**

- Apply the 6 approved items safely, individually, verifiably, reversibly, and auditably.
- Never risk simultaneous loss of both access paths (key SSH + password SSH) — a recovery path exists at every step.
- Close the loop with the existing assessor: findings flip to `ok`, nothing regresses.

**Non-Goals:**

- A reusable plan-execution engine (6 items, one device — PRD §5.6).
- Backup configuration (Q10 TBD), disk-threshold enforcement, Hermes install, or any unapproved hardening.
- Mutating the dev PC or WSL environments during testing.

## Decisions

### D1: One idempotent bash script per item, `check|apply|verify|rollback`

`hardening/apply/items/NN-name.sh` (numbered by *plan item* for traceability) + `hardening/apply/lib.sh` (audit JSONL append, sudo detection, state helpers). Bash because every operation is service/config manipulation where shell is the native idiom, and scripts must be runnable by the operator directly in an SSH session with zero dependencies. Idempotence via state checks before mutation (`apply` on a compliant system reports already-compliant, exits 0, changes nothing). Alternative considered: extending the Python assessor with an apply mode — rejected; mixing the read-only assessor with mutation code would poison its "never modifies the device" contract.

### D2: Safe execution order ≠ plan numbering

Execution order: **02 X11 → 03 rpcbind → 04 avahi → 06 unattended-upgrades → 05 nftables → 01 password-off**. Rationale: run every low-risk item while both access paths still exist; stage the firewall while password auth is still a fallback; remove password auth only when everything else is verified and key access has just been re-proven. The runbook encodes this order; the password script refuses to run (without `--force`) if the audit log lacks verified records for the other five.

### D3: Firewall staged in three gates

1. Write `/etc/nftables.conf` (inet filter: input policy drop; accept `lo`, `ct state established,related`, `tcp dport 22`; output/forward unaffected — forward default accept is irrelevant, no routing role) and `nft -c -f` **syntax-check**.
2. **Non-persistent load** (`nft -f`), keeping the current SSH session (its established flow is covered by the established rule anyway) — then verify a **NEW** SSH connection from the PC succeeds. If the new connection fails, `nft flush ruleset` restores access instantly from the still-open session.
3. Only then `systemctl enable nftables` for boot persistence.

An additional dead-man safety for step 2: before loading, schedule `systemd-run --on-active=3m nft flush ruleset`; cancel the timer after the new-connection check passes. Even a worst-case simultaneous session drop self-heals in 3 minutes.

### D4: Password-auth disable via drop-in, applied last

Use `/etc/ssh/sshd_config.d/10-atlas-hardening.conf` (`PasswordAuthentication no`, plus `X11Forwarding no` from item 02 — same mechanism) rather than sed-editing the stock `sshd_config`: drop-ins are cleanly reversible (delete the file), survive package upgrades, and Debian's stock config includes the directory. `sshd -t` syntax check before `systemctl reload ssh`; reload (not restart) never kills the existing session. Verify by (a) a fresh key-auth connection succeeding and (b) `ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no` being refused.

### D5: Testing without mutating dev environments

Off-device: `bash -n` syntax on all scripts; a review pass of every mutating command against the approved plan; unit-style tests of `lib.sh` helpers (audit record format, already-compliant detection logic) run in WSL using temp dirs and stub commands — read-only toward the environment. The real `apply` executes only on the Pi, one item at a time, gated by its own `verify` — that Pi run is the acceptance evidence (mirrors how the inventory/assessment changes used the Pi as the acceptance environment). Rationale: a throwaway Linux VM would add infrastructure for marginal signal (the Pi is the only environment whose service topology matters), and mutating the user's WSL is not acceptable.

### D6: Agent-driven execution only with `sudo -n`

The scripts are operator-runnable by design. The agent may drive them over SSH only if `sudo -n true` succeeds (passwordless sudo, standard on Raspberry Pi OS first accounts); otherwise the agent prepares the exact commands and the operator runs them. No password is ever entered by automation (hard rule).

## Risks / Trade-offs

- [SSH lockout via firewall] → three-gate staging + established-state rule + dead-man flush timer + password auth still available at that stage + physical console.
- [SSH lockout via password-off with broken key auth] → applied last, only after a fresh key-auth connection succeeds in that same session sequence; rollback is deleting one drop-in file from the console.
- [unattended-upgrades introduces surprise reboots] → Debian default does not auto-reboot; script asserts `Unattended-Upgrade::Automatic-Reboot` is not enabled.
- [avahi disable breaks `raspberrypi.local`] → operator approved knowingly; connection uses the static IP 192.168.0.150; rollback is one systemctl command.
- [apt install pulls unexpected dependencies] → `apt-get install --no-install-recommends`, and the audit log records the transaction; both packages (nftables, unattended-upgrades) are small stock Debian.
- [Scripts drift from the approved plan] → each script header cites plan run id + item; review task compares scripts to the plan line-by-line before any Pi execution.

## Migration Plan

Apply = the runbook itself (order in D2). Rollback = per-item rollback subcommands; full rollback is running all six in reverse order. No data migration.

## Open Questions

- None blocking. Backup destination (Q10) and disk-threshold confirmation remain open project decisions, explicitly outside this change.
