#!/usr/bin/env bash
# Shared library for hardening apply items (change atlas-phase-1-apply-hardening).
# Approved plan: assessment run 20260711T065352Z-0190074a (all 6 items approved
# 2026-07-11; see docs/decisions.md).
#
# Rules enforced here:
# - no credential handling: privilege comes from root or passwordless sudo
#   (sudo -n); otherwise we refuse and hand execution to the operator;
# - every action is audited to var/hardening/apply-log.jsonl;
# - helpers make already-compliant detection cheap so items stay idempotent.

set -euo pipefail

APPLY_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$APPLY_LIB_DIR/../.." && pwd)"
AUDIT_LOG="${ATLAS_APPLY_AUDIT_LOG:-$REPO_ROOT/var/hardening/apply-log.jsonl}"
PLAN_RUN_ID="20260711T065352Z-0190074a"

_json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/ }"
    s="${s//$'\t'/ }"
    printf '%s' "$s"
}

# audit <item> <action> <outcome> <detail>
audit() {
    local item="$1" action="$2" outcome="$3" detail="${4:-}"
    mkdir -p "$(dirname "$AUDIT_LOG")"
    printf '{"ts":"%s","plan":"%s","item":"%s","action":"%s","outcome":"%s","detail":"%s","user":"%s"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$PLAN_RUN_ID" \
        "$(_json_escape "$item")" "$(_json_escape "$action")" \
        "$(_json_escape "$outcome")" "$(_json_escape "$detail")" \
        "$(_json_escape "$(id -un)")" >> "$AUDIT_LOG"
}

# priv <cmd...> — run privileged WITHOUT ever prompting for a password.
priv() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif sudo -n true 2>/dev/null; then
        sudo -n "$@"
    else
        echo "REFUSING: privilege required and passwordless sudo (sudo -n) is" >&2
        echo "not available. Run this item yourself in your own sudo session:" >&2
        echo "  sudo $0 ${ITEM_ACTION:-<action>}" >&2
        return 78  # EX_CONFIG-ish: operator action required
    fi
}

have_priv() {
    [ "$(id -u)" -eq 0 ] || sudo -n true 2>/dev/null
}

# unit_state <unit> -> "enabled/active", "not-found", etc. (never fails the script)
unit_enabled() { systemctl is-enabled "$1" 2>/dev/null || true; }
unit_active() { systemctl is-active "$1" 2>/dev/null || true; }
unit_exists() {
    systemctl list-unit-files --no-legend --no-pager "$1" 2>/dev/null | grep -q . \
        || systemctl status "$1" >/dev/null 2>&1
}

# sshd_effective <key> — effective sshd config value (needs privilege)
sshd_effective() {
    priv /usr/sbin/sshd -T 2>/dev/null | awk -v k="$1" '$1==k {print $2; exit}'
}

# port_listening <port> — any listener on the TCP/UDP port?
port_listening() {
    ss -tuln 2>/dev/null | awk '{print $5}' | grep -Eq "[:.]$1\$"
}

# audit_has_ok <item> <action> — has this item+action succeeded before?
audit_has_ok() {
    [ -f "$AUDIT_LOG" ] && grep -q "\"item\":\"$1\",\"action\":\"$2\",\"outcome\":\"ok\"" "$AUDIT_LOG"
}

die() {
    local item="$1" action="$2" msg="$3"
    audit "$item" "$action" "failed" "$msg"
    echo "FAILED [$item $action]: $msg" >&2
    exit 1
}

ok() {
    local item="$1" action="$2" msg="$3"
    audit "$item" "$action" "ok" "$msg"
    echo "OK [$item $action]: $msg"
}
