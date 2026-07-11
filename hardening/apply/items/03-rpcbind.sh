#!/usr/bin/env bash
# Plan 20260711T065352Z-0190074a item 3: disable rpcbind (port 111, unused).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../lib.sh"

ITEM="03-rpcbind"
ITEM_ACTION="${1:-}"

case "${1:-}" in
  check)
    echo "rpcbind.socket:  enabled=$(unit_enabled rpcbind.socket) active=$(unit_active rpcbind.socket)"
    echo "rpcbind.service: enabled=$(unit_enabled rpcbind.service) active=$(unit_active rpcbind.service)"
    echo "port 111 listening: $(port_listening 111 && echo yes || echo no)"
    audit "$ITEM" check ok "inspected"
    ;;
  apply)
    if ! unit_exists rpcbind.service && ! unit_exists rpcbind.socket; then
      ok "$ITEM" apply "already-compliant (rpcbind not installed)"; exit 0
    fi
    if [ "$(unit_active rpcbind.socket)" != "active" ] && [ "$(unit_active rpcbind.service)" != "active" ] \
       && [ "$(unit_enabled rpcbind.socket)" != "enabled" ]; then
      ok "$ITEM" apply "already-compliant (disabled and inactive)"; exit 0
    fi
    priv systemctl disable --now rpcbind.socket rpcbind.service
    ok "$ITEM" apply "rpcbind socket+service disabled and stopped"
    ;;
  verify)
    if [ "$(unit_active rpcbind.service)" = "active" ] || [ "$(unit_active rpcbind.socket)" = "active" ]; then
      die "$ITEM" verify "rpcbind still active"
    fi
    port_listening 111 && die "$ITEM" verify "something still listens on port 111"
    ok "$ITEM" verify "rpcbind inactive, port 111 closed"
    ;;
  rollback)
    priv systemctl enable --now rpcbind.socket
    ok "$ITEM" rollback "rpcbind.socket re-enabled"
    ;;
  *) echo "usage: $0 check|apply|verify|rollback" >&2; exit 2 ;;
esac
