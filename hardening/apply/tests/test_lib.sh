#!/usr/bin/env bash
# Off-device tests for hardening/apply/lib.sh (task 3.1).
# Uses temp dirs and stubs only — never touches system state or privilege.
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
export ATLAS_APPLY_AUDIT_LOG="$TMP/apply-log.jsonl"
FAILURES=0

fail() { echo "FAIL: $*" >&2; FAILURES=$((FAILURES + 1)); }
pass() { echo "ok:   $*"; }

# shellcheck source=../lib.sh
source "$HERE/../lib.sh"

# --- audit record shape -------------------------------------------------------
audit "test-item" "apply" "ok" 'detail with "quotes" and \backslash and
newline'
LINE="$(tail -1 "$ATLAS_APPLY_AUDIT_LOG")"
echo "$LINE" | python3 -c "import json,sys; json.loads(sys.stdin.read())" \
    && pass "audit record is valid JSON" || fail "audit record is not valid JSON: $LINE"
echo "$LINE" | grep -q '"item":"test-item"' && pass "item recorded" || fail "item missing"
echo "$LINE" | grep -q '"plan":"20260711T065352Z-0190074a"' && pass "plan id recorded" || fail "plan id missing"

# --- audit_has_ok --------------------------------------------------------------
audit_has_ok "test-item" "apply" && pass "audit_has_ok finds ok record" || fail "audit_has_ok missed ok record"
audit_has_ok "test-item" "verify" && fail "audit_has_ok false positive" || pass "audit_has_ok rejects absent action"
audit "test-item" "verify" "failed" "boom"
audit_has_ok "test-item" "verify" && fail "failed outcome counted as ok" || pass "failed outcome not counted as ok"

# --- ok/die helpers -------------------------------------------------------------
( ok "test-item" "verify" "fine" ) >/dev/null && pass "ok() exits zero" || fail "ok() nonzero"
( die "test-item" "verify" "boom2" ) >/dev/null 2>&1 && fail "die() exited zero" || pass "die() exits nonzero"
grep -q '"outcome":"failed","detail":"boom2"' "$ATLAS_APPLY_AUDIT_LOG" \
    && pass "die() audited the failure" || fail "die() did not audit"

# --- priv refuses without a password (in an environment lacking sudo -n) --------
if [ "$(id -u)" -ne 0 ] && ! sudo -n true 2>/dev/null; then
    ( priv true ) >/dev/null 2>&1 && fail "priv ran without privilege" \
        || pass "priv refuses without passwordless sudo (no prompt)"
else
    pass "priv refusal untestable here (privilege available) — skipped"
fi

# --- item scripts: prerequisite gate logic (01 refuses without audit records) ---
export ATLAS_APPLY_AUDIT_LOG="$TMP/empty-log.jsonl"
OUT="$(bash "$HERE/../items/01-ssh-password.sh" apply 2>&1)" && RC=0 || RC=$?
[ "$RC" -ne 0 ] && echo "$OUT" | grep -q "refusing" \
    && pass "01-ssh-password refuses without verified prerequisites" \
    || fail "01-ssh-password did not refuse (rc=$RC): $OUT"

# --- regression: grep -q on a pipe must not SIGPIPE-fail under pipefail --------
# A large producer piped into `grep -q` (which exits on first match) returns
# 141 under `set -o pipefail`. Verify our capture-then-here-string pattern is
# immune. This is the bug that made 05-nftables verify falsely fail.
set -o pipefail
big="$(seq 1 100000; echo MATCH_TOKEN; seq 1 100000)"
if grep -q MATCH_TOKEN <<<"$big"; then pass "here-string grep -q survives pipefail"
else fail "here-string grep -q failed under pipefail"; fi
# demonstrate the OLD broken form would have failed (informational, not a gate)
if seq 1 100000 | { echo MATCH_TOKEN; cat >/dev/null; } | grep -q MATCH_TOKEN 2>/dev/null; then :; fi

echo
if [ "$FAILURES" -eq 0 ]; then echo "LIB TESTS PASSED"; exit 0;
else echo "LIB TESTS FAILED: $FAILURES"; exit 1; fi
