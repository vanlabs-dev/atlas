# Apply-script command review

**Change:** `atlas-phase-1-apply-hardening`, task 3.2
**Reviewed:** 2026-07-11, scripts at commit time vs the approved plan
(assessment run `20260711T065352Z-0190074a`, all 6 items operator-approved).

Method: every privileged/mutating command in `hardening/apply/` was listed and
compared to its plan item's "commands that WOULD run". Deviations are
deliberate safety improvements, noted per item. No script contains any
mutation outside its item's scope; no script handles credentials.

## Item 1 — SSH key-only auth (`01-ssh-password.sh`)

| Mutating command | Plan conformance |
|---|---|
| `tee /etc/ssh/sshd_config.d/10-atlas-item01-password.conf` (`PasswordAuthentication no`) | ✅ Deviation (improvement): plan proposed `sed` on the stock `sshd_config`; a drop-in achieves the same effective config (Debian includes the dir first; first value wins), is upgrade-safe, and rollback is one `rm`. |
| `/usr/sbin/sshd -t` | ✅ read-only syntax gate, added safety |
| `systemctl reload ssh` | ✅ per plan; reload never drops the live session |

Extra safety beyond plan: refuses to run before all other items have verified
`ok` audit records (`--force` to override).

## Item 2 — X11Forwarding off (`02-x11-forwarding.sh`)

Same mechanism as item 1 (drop-in `20-atlas-item02-x11.conf`, `sshd -t`,
`reload ssh`). ✅ conforms with the same sed→drop-in improvement.

## Item 3 — rpcbind (`03-rpcbind.sh`)

| Mutating command | Plan conformance |
|---|---|
| `systemctl disable --now rpcbind.socket rpcbind.service` | ✅ exactly the plan command |

## Item 4 — avahi (`04-avahi.sh`)

| Mutating command | Plan conformance |
|---|---|
| `systemctl disable --now avahi-daemon.socket avahi-daemon.service` | ✅ exactly the plan command |

## Item 5 — nftables (`05-nftables.sh`)

| Mutating command | Plan conformance |
|---|---|
| `apt-get update -qq` + `apt-get install -y --no-install-recommends nftables` | ✅ plan: `apt install nftables`; `--no-install-recommends` narrows it |
| `tee /etc/nftables.conf` (input policy drop; accept lo, established/related, tcp 22, icmp/icmpv6) | ✅ plan's described ruleset, plus icmp/icmpv6 accepts (required for IPv6 neighbor discovery and path MTU — omitting them can break connectivity in ways the plan did not intend) and `ct state invalid drop` |
| `systemd-run --on-active=3m --unit=atlas-nft-deadman nft flush ruleset` | ✅ addition (design D3 dead-man); auto-reverts to pre-item state, mutation window bounded to 3 minutes |
| `nft -f /etc/nftables.conf` | ✅ plan; staged non-persistent first |
| `systemctl enable nftables.service` | ✅ plan's "enable --now" split across the confirm gate |
| `systemctl stop atlas-nft-deadman.timer` / `reset-failed` | ✅ dead-man lifecycle only |

## Item 6 — unattended upgrades (`06-unattended-upgrades.sh`)

| Mutating command | Plan conformance |
|---|---|
| `apt-get update -qq` + `apt-get install -y --no-install-recommends unattended-upgrades` | ✅ plan command, narrowed |
| `tee /etc/apt/apt.conf.d/20auto-upgrades` (Update-Package-Lists "1", Unattended-Upgrade "1") | ✅ equivalent of the plan's `dpkg-reconfigure -plow` outcome, deterministic and non-interactive |

Verify additionally asserts `Unattended-Upgrade::Automatic-Reboot` is not
enabled (design risk item).

## Cross-cutting

- `lib.sh` mutates nothing except appending to `var/hardening/apply-log.jsonl`.
- All privilege flows through `priv()` → root or `sudo -n`; no password path
  exists (verified by test in an environment without passwordless sudo).
- `bash -n` passes on all scripts; lib tests pass in WSL.

**Verdict: scripts conform to the approved plan; all deviations are
documented safety improvements within item scope.**
