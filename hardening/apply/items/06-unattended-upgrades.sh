#!/usr/bin/env bash
# Plan 20260711T065352Z-0190074a item 6: unattended security updates.
# Asserts automatic reboot stays OFF (Debian default).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../lib.sh"

ITEM="06-unattended-upgrades"
AUTOCONF="/etc/apt/apt.conf.d/20auto-upgrades"
ITEM_ACTION="${1:-}"

periodic_enabled() {
  local v; v="$(apt-config dump APT::Periodic::Unattended-Upgrade 2>/dev/null || true)"
  grep -q '"1"' <<<"$v"
}

case "${1:-}" in
  check)
    echo "package installed: $(dpkg -s unattended-upgrades >/dev/null 2>&1 && echo yes || echo no)"
    echo "periodic unattended-upgrade enabled: $(periodic_enabled && echo yes || echo no)"
    echo "auto-reboot: $(apt-config dump Unattended-Upgrade::Automatic-Reboot 2>/dev/null || echo '(unset)')"
    audit "$ITEM" check ok "inspected"
    ;;
  apply)
    if dpkg -s unattended-upgrades >/dev/null 2>&1 && periodic_enabled; then
      ok "$ITEM" apply "already-compliant"; exit 0
    fi
    if ! dpkg -s unattended-upgrades >/dev/null 2>&1; then
      priv env DEBIAN_FRONTEND=noninteractive apt-get update -qq
      priv env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends unattended-upgrades \
        || die "$ITEM" apply "apt-get install unattended-upgrades failed"
    fi
    printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
      | priv tee "$AUTOCONF" >/dev/null
    ok "$ITEM" apply "package installed, periodic security upgrades enabled"
    ;;
  verify)
    dpkg -s unattended-upgrades >/dev/null 2>&1 || die "$ITEM" verify "package not installed"
    periodic_enabled || die "$ITEM" verify "APT::Periodic::Unattended-Upgrade not 1"
    REBOOT="$(apt-config dump Unattended-Upgrade::Automatic-Reboot 2>/dev/null || true)"
    if grep -q '"true"' <<<"$REBOOT"; then
      die "$ITEM" verify "Automatic-Reboot is enabled — plan requires it OFF"
    fi
    ok "$ITEM" verify "enabled, no automatic reboot"
    ;;
  rollback)
    printf 'APT::Periodic::Update-Package-Lists "0";\nAPT::Periodic::Unattended-Upgrade "0";\n' \
      | priv tee "$AUTOCONF" >/dev/null
    ok "$ITEM" rollback "periodic runs disabled (package left installed)"
    ;;
  *) echo "usage: $0 check|apply|verify|rollback" >&2; exit 2 ;;
esac
