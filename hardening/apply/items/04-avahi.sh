#!/usr/bin/env bash
# Plan 20260711T065352Z-0190074a item 4: disable avahi-daemon (mDNS).
# Operator approved knowingly: raspberrypi.local resolution stops; use the IP.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../lib.sh"

ITEM="04-avahi"
ITEM_ACTION="${1:-}"

case "${1:-}" in
  check)
    echo "avahi-daemon.socket:  enabled=$(unit_enabled avahi-daemon.socket) active=$(unit_active avahi-daemon.socket)"
    echo "avahi-daemon.service: enabled=$(unit_enabled avahi-daemon.service) active=$(unit_active avahi-daemon.service)"
    echo "port 5353 listening: $(port_listening 5353 && echo yes || echo no)"
    audit "$ITEM" check ok "inspected"
    ;;
  apply)
    if ! unit_exists avahi-daemon.service && ! unit_exists avahi-daemon.socket; then
      ok "$ITEM" apply "already-compliant (avahi not installed)"; exit 0
    fi
    if [ "$(unit_active avahi-daemon.service)" != "active" ] && [ "$(unit_active avahi-daemon.socket)" != "active" ] \
       && [ "$(unit_enabled avahi-daemon.service)" != "enabled" ]; then
      ok "$ITEM" apply "already-compliant (disabled and inactive)"; exit 0
    fi
    priv systemctl disable --now avahi-daemon.socket avahi-daemon.service
    ok "$ITEM" apply "avahi socket+service disabled and stopped"
    ;;
  verify)
    if [ "$(unit_active avahi-daemon.service)" = "active" ] || [ "$(unit_active avahi-daemon.socket)" = "active" ]; then
      die "$ITEM" verify "avahi still active"
    fi
    ok "$ITEM" verify "avahi inactive"
    ;;
  rollback)
    priv systemctl enable --now avahi-daemon.service
    ok "$ITEM" rollback "avahi-daemon re-enabled"
    ;;
  *) echo "usage: $0 check|apply|verify|rollback" >&2; exit 2 ;;
esac
