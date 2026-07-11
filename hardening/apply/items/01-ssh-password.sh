#!/usr/bin/env bash
# Plan 20260711T065352Z-0190074a item 1: SSH key-only authentication.
# MUST RUN LAST: refuses (without --force) until items 02,03,04,06,05 have
# verified `ok` records in the audit log. Re-verify a fresh key-auth login
# immediately before applying. Rollback = delete one drop-in (console-safe).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../lib.sh"

ITEM="01-ssh-password"
DROPIN="/etc/ssh/sshd_config.d/10-atlas-item01-password.conf"
PREREQ_ITEMS=(02-x11-forwarding 03-rpcbind 04-avahi 06-unattended-upgrades 05-nftables)
ITEM_ACTION="${1:-}"

prereqs_verified() {
  local item
  for item in "${PREREQ_ITEMS[@]}"; do
    audit_has_ok "$item" verify || { echo "prerequisite not verified: $item" >&2; return 1; }
  done
}

case "${1:-}" in
  check)
    echo "effective passwordauthentication: $(sshd_effective passwordauthentication || echo 'unknown (need priv)')"
    echo "drop-in present: $([ -f "$DROPIN" ] && echo yes || echo no)"
    echo "prerequisites verified: $(prereqs_verified >/dev/null 2>&1 && echo yes || echo no)"
    audit "$ITEM" check ok "inspected"
    ;;
  apply)
    if [ "${2:-}" != "--force" ] && ! prereqs_verified; then
      die "$ITEM" apply "refusing: run and verify all other items first (or --force)"
    fi
    if [ "$(sshd_effective passwordauthentication)" = "no" ] && [ -f "$DROPIN" ]; then
      ok "$ITEM" apply "already-compliant"; exit 0
    fi
    printf '# Atlas hardening item 1 (plan %s)\nPasswordAuthentication no\n' "$PLAN_RUN_ID" \
      | priv tee "$DROPIN" >/dev/null
    priv /usr/sbin/sshd -t || { priv rm -f "$DROPIN"; die "$ITEM" apply "sshd -t rejected config; drop-in removed"; }
    priv systemctl reload ssh
    ok "$ITEM" apply "PasswordAuthentication no via drop-in; sshd reloaded"
    echo ""
    echo ">>> GATE: from another machine, verify a fresh KEY login still works,"
    echo ">>> and that password auth is refused, then run: bash $0 verify"
    ;;
  verify)
    [ "$(sshd_effective passwordauthentication)" = "no" ] \
      && ok "$ITEM" verify "effective PasswordAuthentication is no" \
      || die "$ITEM" verify "effective PasswordAuthentication is not no"
    ;;
  rollback)
    priv rm -f "$DROPIN"
    priv /usr/sbin/sshd -t && priv systemctl reload ssh
    ok "$ITEM" rollback "drop-in removed; password auth back to distro default"
    ;;
  *) echo "usage: $0 check|apply [--force]|verify|rollback" >&2; exit 2 ;;
esac
