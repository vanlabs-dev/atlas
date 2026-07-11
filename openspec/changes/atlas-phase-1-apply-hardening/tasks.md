# Tasks: atlas-phase-1-apply-hardening

## 1. Shared library and scaffolding

- [ ] 1.1 Create `hardening/apply/` layout with `lib.sh` (JSONL audit append to `var/hardening/apply-log.jsonl`, `sudo -n` detection, already-compliant helpers, stop-on-failure conventions) and a runbook README stating the safe execution order (02→03→04→06→05→01), the lockout-prevention protocol, and the no-credential rule

## 2. Item scripts (each: check | apply | verify | rollback, idempotent, plan-cited)

- [ ] 2.1 `02-x11-forwarding.sh` — sshd drop-in `X11Forwarding no`, `sshd -t` check, reload (not restart), verify via `sshd -T`
- [ ] 2.2 `03-rpcbind.sh` — disable rpcbind socket+service, verify port 111 no longer listening
- [ ] 2.3 `04-avahi.sh` — disable avahi socket+service, verify port 5353 no longer bound by avahi
- [ ] 2.4 `06-unattended-upgrades.sh` — install (`--no-install-recommends`) and enable periodic security updates; assert auto-reboot is NOT enabled; verify via apt config
- [ ] 2.5 `05-nftables.sh` — write `/etc/nftables.conf` (input policy drop; accept lo, established/related, tcp 22), `nft -c` syntax gate, dead-man flush timer, non-persistent load, new-SSH-connection gate, then persist via `systemctl enable nftables`
- [ ] 2.6 `01-ssh-password.sh` — sshd drop-in `PasswordAuthentication no`, refuses to run while other items lack verified audit records (unless `--force`), `sshd -t` + reload, verify fresh key-auth login succeeds and password auth is refused

## 3. Off-device verification (no dev-environment mutation)

- [ ] 3.1 `bash -n` all scripts; lib helper tests (audit record shape, compliant-detection) runnable in WSL against temp dirs and stubs only
- [ ] 3.2 Review pass: line-by-line comparison of every mutating command against the approved plan items (run `20260711T065352Z-0190074a`); record the review in the change

## 4. Gated Pi execution (the acceptance run)

- [ ] 4.1 Preflight on the Pi: `git pull`, `sudo -n` capability check (determines agent-driven vs operator-driven), all six `check` subcommands pass and report current state
- [ ] 4.2 Apply and verify low-risk items in order: 02 X11, 03 rpcbind, 04 avahi, 06 unattended-upgrades — one at a time, stop on any verify failure
- [ ] 4.3 Apply 05 nftables through all three gates (syntax → non-persistent load + NEW SSH connection verified → persist); dead-man timer cancelled only after the gate passes
- [ ] 4.4 Re-verify fresh key-auth SSH, then apply 01 password-off; verify key login works and password auth is refused
- [ ] 4.5 Closed-loop acceptance: re-run the hardening assessor — ssh-authentication-and-exposed-ports, firewall-rules, unattended-security-updates flip to `ok` with no regressions; record the run id and outcome in docs/decisions.md
