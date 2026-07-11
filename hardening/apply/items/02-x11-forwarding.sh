#!/usr/bin/env bash
# Plan 20260711T065352Z-0190074a item 2: X11Forwarding no.
# Mechanism: sshd drop-in (cleanly reversible, upgrade-safe); reload not restart.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../lib.sh"

ITEM="02-x11-forwarding"
DROPIN="/etc/ssh/sshd_config.d/20-atlas-item02-x11.conf"
ITEM_ACTION="${1:-}"

case "${1:-}" in
  check)
    echo "effective x11forwarding: $(sshd_effective x11forwarding || echo 'unknown (need priv)')"
    echo "drop-in present: $([ -f "$DROPIN" ] && echo yes || echo no)"
    audit "$ITEM" check ok "inspected"
    ;;
  apply)
    if [ "$(sshd_effective x11forwarding)" = "no" ] && [ -f "$DROPIN" ]; then
      ok "$ITEM" apply "already-compliant"; exit 0
    fi
    printf '# Atlas hardening item 2 (plan %s)\nX11Forwarding no\n' "$PLAN_RUN_ID" \
      | priv tee "$DROPIN" >/dev/null
    priv /usr/sbin/sshd -t || { priv rm -f "$DROPIN"; die "$ITEM" apply "sshd -t rejected config; drop-in removed"; }
    priv systemctl reload ssh
    ok "$ITEM" apply "drop-in written, sshd reloaded"
    ;;
  verify)
    [ "$(sshd_effective x11forwarding)" = "no" ] \
      && ok "$ITEM" verify "effective X11Forwarding is no" \
      || die "$ITEM" verify "effective X11Forwarding is not no"
    ;;
  rollback)
    priv rm -f "$DROPIN"
    priv /usr/sbin/sshd -t && priv systemctl reload ssh
    ok "$ITEM" rollback "drop-in removed, sshd reloaded"
    ;;
  *) echo "usage: $0 check|apply|verify|rollback" >&2; exit 2 ;;
esac
