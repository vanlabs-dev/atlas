# Hardening apply runbook

Implements the 6 operator-approved items from hardening plan run
`20260711T065352Z-0190074a` (OpenSpec change `atlas-phase-1-apply-hardening`).
This is the **only** part of the repo that mutates the device, and it applies
nothing that is not in the approved plan.

## Rules

- **One item at a time**, in the safe order below. A failed `verify` stops the
  sequence — do not continue past a failure.
- **No credentials, ever**: scripts obtain privilege from root or passwordless
  `sudo -n` only. If `sudo -n` is unavailable they refuse and print the exact
  command for the operator to run.
- Every `check`/`apply`/`verify`/`rollback` appends to
  `var/hardening/apply-log.jsonl` (gitignored).
- All items are **idempotent**: `apply` on a compliant system reports
  already-compliant and changes nothing.

## Safe execution order (NOT plan numbering)

| Step | Script | Plan item | Risk note |
|---|---|---|---|
| 1 | `items/02-x11-forwarding.sh` | 2 | low — sshd reload never drops sessions |
| 2 | `items/03-rpcbind.sh` | 3 | low |
| 3 | `items/04-avahi.sh` | 4 | low — loses `raspberrypi.local`; use the IP |
| 4 | `items/06-unattended-upgrades.sh` | 6 | low — asserts no auto-reboot |
| 5 | `items/05-nftables.sh` | 5 | **gated** — see lockout protocol |
| 6 | `items/01-ssh-password.sh` | 1 | **last** — refuses to run early |

## Lockout-prevention protocol

1. Keep the working SSH session open for the whole sequence.
2. **Firewall (step 5)** is three-gated: `apply` syntax-checks the ruleset,
   arms a 3-minute dead-man timer that auto-flushes the ruleset, and loads it
   non-persistently. Then, from another machine, **open a NEW SSH connection**.
   Only if it succeeds run `05-nftables.sh confirm`, which disarms the timer,
   reloads the ruleset, and enables boot persistence. If the new connection
   fails, either flush from the open session (`sudo nft flush ruleset`) or
   just wait ≤3 minutes for the dead-man timer.
3. **Password-auth disable (step 6)** runs only after steps 1–5 have verified
   `ok` records in the audit log (it checks; `--force` overrides). Before
   applying, confirm a fresh key-auth login works. Rollback is deleting one
   drop-in file — possible from the physical console at worst.

## Usage

```sh
# on the Pi, in the repo checkout
bash hardening/apply/items/02-x11-forwarding.sh check    # read-only
bash hardening/apply/items/02-x11-forwarding.sh apply
bash hardening/apply/items/02-x11-forwarding.sh verify
# ... next item
```

Acceptance: after all six, re-run `python3 hardening/atlas_hardening.py assess`
— `ssh-authentication-and-exposed-ports`, `firewall-rules`, and
`unattended-security-updates` must report `ok` with no regressions elsewhere.
