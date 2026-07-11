#!/usr/bin/env bash
# Integration test for the hardening assessor (task 5.1 of
# atlas-phase-0-hardening-assessment). Runs on real Linux (WSL/container).
#
# Flow: real inventory run -> real assessment run -> assertions:
#   1. assessor exits 0 or 3, never 1;
#   2. assessment JSON validates against schema v1 with all 11 areas;
#   3. plan + audit written, 0600;
#   4. read-only: packages/units/cron unchanged, no files modified outside
#      the output dirs.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
WORKDIR="$(mktemp -d)"
INV_OUT="$WORKDIR/inv"
HARD_OUT="$WORKDIR/hard"
FAILURES=0

fail() { echo "FAIL: $*" >&2; FAILURES=$((FAILURES + 1)); }
pass() { echo "ok:   $*"; }

command -v python3 >/dev/null || { echo "python3 required"; exit 2; }

snapshots() {
    local phase="$1"
    { dpkg-query -W 2>/dev/null || echo na; } | sort >"$WORKDIR/packages.$phase"
    # transient units (session-N.scope etc.) are logind runtime noise, not files
    { systemctl list-unit-files --no-pager --plain 2>/dev/null || echo na; } \
        | grep -v ' transient ' | grep -v '^[0-9]* unit files' | sort >"$WORKDIR/units.$phase"
    { crontab -l 2>/dev/null || echo na; } >"$WORKDIR/cron.$phase"
}

# Let systemd finish first-boot activity so the baseline snapshot is stable
# (fresh WSL instances generate/settle units for the first minute).
systemctl is-system-running --wait >/dev/null 2>&1 || true

snapshots before
MARKER="$WORKDIR/marker"
touch "$MARKER"
sleep 1

python3 "$REPO_DIR/inventory/atlas_inventory.py" run --output-dir "$INV_OUT" >/dev/null
INV_RC=$?
{ [ "$INV_RC" -eq 0 ] || [ "$INV_RC" -eq 3 ]; } && pass "inventory exit $INV_RC" || fail "inventory exit $INV_RC"

REPORT=$(ls "$INV_OUT"/report-*.json | head -1)
python3 "$REPO_DIR/hardening/atlas_hardening.py" assess \
    --inventory-report "$REPORT" --output-dir "$HARD_OUT"
RC=$?
{ [ "$RC" -eq 0 ] || [ "$RC" -eq 3 ]; } && pass "assessor exit $RC" || fail "assessor exit $RC (expected 0/3)"

snapshots after
for pair in packages units cron; do
    diff -q "$WORKDIR/$pair.before" "$WORKDIR/$pair.after" >/dev/null \
        && pass "$pair unchanged" || fail "$pair changed"
done
CHANGED=$(find /etc /opt /srv /var/spool/cron -newer "$MARKER" -type f 2>/dev/null | head -20)
[ -z "$CHANGED" ] && pass "no files modified in /etc /opt /srv /var/spool/cron" \
    || fail "files modified: $CHANGED"

ASSESSMENT=$(ls "$HARD_OUT"/assessment-*.json 2>/dev/null | head -1)
PLAN=$(ls "$HARD_OUT"/hardening-plan-*.md 2>/dev/null | head -1)
AUDIT=$(ls "$HARD_OUT"/audit-*.json 2>/dev/null | head -1)
[ -n "$ASSESSMENT" ] && pass "assessment written" || fail "assessment missing"
[ -n "$PLAN" ] && pass "plan written" || fail "plan missing"
[ -n "$AUDIT" ] && pass "audit written" || fail "audit missing"

if [ -n "$ASSESSMENT" ]; then
    for f in "$ASSESSMENT" "$PLAN" "$AUDIT"; do
        MODE=$(stat -c %a "$f")
        [ "$MODE" = "600" ] && pass "$(basename "$f") mode 600" || fail "$(basename "$f") mode $MODE"
    done
    python3 - "$ASSESSMENT" "$REPO_DIR" <<'PYEOF'
import json, sys, os
assessment_path, repo = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(repo, "hardening"))
import atlas_hardening as ah

assessment = json.load(open(assessment_path))
errors = ah.inv.schema_validate(assessment, ah.ASSESSMENT_SCHEMA)
assert not errors, errors[:10]
print("ok:   assessment validates against schema v%d" % ah.ASSESSMENT_SCHEMA_VERSION)
areas = [a["area"] for a in assessment["areas"]]
assert areas == list(ah.AREAS), areas
print("ok:   all 11 areas present in fixed order")
verdicts = {}
for area in assessment["areas"]:
    verdicts[area["verdict"]] = verdicts.get(area["verdict"], 0) + 1
print("ok:   verdicts: %s" % verdicts)
assert assessment["consumed_inventory"]["run_id"], "inventory reference missing"
print("ok:   consumed inventory reference recorded")
PYEOF
    [ $? -eq 0 ] || fail "assessment content assertions failed"
fi

echo
if [ "$FAILURES" -eq 0 ]; then
    echo "INTEGRATION TEST PASSED ($WORKDIR)"
    exit 0
else
    echo "INTEGRATION TEST FAILED: $FAILURES failure(s) ($WORKDIR)"
    exit 1
fi
