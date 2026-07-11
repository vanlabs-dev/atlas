#!/usr/bin/env bash
# Plan 20260711T065352Z-0190074a item 5: nftables default-deny inbound.
# THREE-GATED (lockout prevention):
#   apply   = install + write config + `nft -c` syntax gate + arm 3-min
#             dead-man flush timer + non-persistent load.
#             >>> then verify a NEW SSH connection from another machine <<<
#   confirm = disarm dead-man, reload ruleset, enable boot persistence.
#   If the new connection fails: `sudo nft flush ruleset` from the open
#   session, or wait <=3 minutes for the dead-man timer.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../lib.sh"

ITEM="05-nftables"
CONF="/etc/nftables.conf"
DEADMAN_UNIT="atlas-nft-deadman"
ITEM_ACTION="${1:-}"

write_config() {
  priv tee "$CONF" >/dev/null <<NFTEOF
#!/usr/sbin/nft -f
# Atlas hardening item 5 (plan $PLAN_RUN_ID): default-deny inbound.
flush ruleset
table inet filter {
  chain input {
    type filter hook input priority 0; policy drop;
    iif "lo" accept
    ct state established,related accept
    ct state invalid drop
    tcp dport 22 accept
    ip protocol icmp accept
    meta l4proto ipv6-icmp accept
  }
  chain forward {
    type filter hook forward priority 0; policy accept;
  }
  chain output {
    type filter hook output priority 0; policy accept;
  }
}
NFTEOF
}

ruleset_active() {
  # capture then match: grep -q on a pipe SIGPIPEs nft under `set -o pipefail`
  local rs; rs="$(priv nft list ruleset 2>/dev/null || true)"
  grep -q "policy drop" <<<"$rs"
}

case "${1:-}" in
  check)
    echo "nftables installed: $(dpkg -s nftables >/dev/null 2>&1 && echo yes || echo no)"
    echo "config present: $([ -f "$CONF" ] && echo yes || echo no)"
    echo "default-deny ruleset active: $(ruleset_active && echo yes || echo no)"
    echo "nftables.service enabled: $(unit_enabled nftables.service)"
    audit "$ITEM" check ok "inspected"
    ;;
  apply)
    if ruleset_active && [ "$(unit_enabled nftables.service)" = "enabled" ]; then
      ok "$ITEM" apply "already-compliant"; exit 0
    fi
    if ! dpkg -s nftables >/dev/null 2>&1; then
      priv env DEBIAN_FRONTEND=noninteractive apt-get update -qq
      priv env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nftables \
        || die "$ITEM" apply "apt-get install nftables failed"
    fi
    write_config
    priv nft -c -f "$CONF" || die "$ITEM" apply "nft syntax check rejected $CONF"
    # dead-man: auto-flush in 3 minutes unless confirm disarms it
    priv systemctl stop "$DEADMAN_UNIT.timer" 2>/dev/null || true
    priv systemd-run --on-active=3m --unit="$DEADMAN_UNIT" /usr/sbin/nft flush ruleset \
      || die "$ITEM" apply "could not arm dead-man timer; NOT loading ruleset"
    priv nft -f "$CONF" || { priv systemctl stop "$DEADMAN_UNIT.timer" 2>/dev/null || true; \
                             die "$ITEM" apply "nft load failed; dead-man disarmed"; }
    ok "$ITEM" apply "ruleset loaded NON-PERSISTENTLY; dead-man flush in 3m"
    echo ""
    echo ">>> GATE: open a NEW SSH connection from another machine NOW."
    echo ">>> If it works:  bash $0 confirm   (within 3 minutes)"
    echo ">>> If it fails:  sudo nft flush ruleset   (or wait for the timer)"
    ;;
  confirm)
    priv systemctl stop "$DEADMAN_UNIT.timer" 2>/dev/null || true
    priv systemctl reset-failed "$DEADMAN_UNIT.service" 2>/dev/null || true
    priv nft -f "$CONF" || die "$ITEM" confirm "reload of $CONF failed"
    priv systemctl enable nftables.service
    ok "$ITEM" confirm "dead-man disarmed; ruleset persisted (enabled at boot)"
    ;;
  verify)
    ruleset_active || die "$ITEM" verify "default-deny ruleset not active"
    [ "$(unit_enabled nftables.service)" = "enabled" ] || die "$ITEM" verify "nftables.service not enabled"
    RS="$(priv nft list ruleset 2>/dev/null || true)"
    grep -q "tcp dport 22 accept" <<<"$RS" || die "$ITEM" verify "SSH allow rule missing"
    ok "$ITEM" verify "default-deny active with SSH allowed; persistent at boot"
    ;;
  rollback)
    priv nft flush ruleset
    priv systemctl disable nftables.service 2>/dev/null || true
    ok "$ITEM" rollback "ruleset flushed, service disabled (config left at $CONF)"
    ;;
  *) echo "usage: $0 check|apply|confirm|verify|rollback" >&2; exit 2 ;;
esac
