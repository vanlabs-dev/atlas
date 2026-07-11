#!/usr/bin/env bash
# Integration test for the Atlas device inventory (task 6.1 of
# atlas-phase-0-device-inventory). Runs on a real Linux environment
# (WSL or a container) — NOT on the target Pi.
#
# Verifies:
#   1. a full unprivileged run exits 0 (complete) or 3 (partial), never 1;
#   2. the report validates against schema v1 and every ATLAS-ENV-001
#      category is present with explicit per-item statuses;
#   3. worksheet and audit record are produced;
#   4. read-only property: package list, systemd unit files, and crontab are
#      unchanged, and no file outside the output directory was modified
#      during the run (checked via a find -newer marker sweep of /etc, /opt,
#      /srv and cron spools);
#   5. outputs have 0600 permissions.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVENTORY_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKDIR="$(mktemp -d)"
OUTDIR="$WORKDIR/out"
FAILURES=0

fail() { echo "FAIL: $*" >&2; FAILURES=$((FAILURES + 1)); }
pass() { echo "ok:   $*"; }

command -v python3 >/dev/null || { echo "python3 required"; exit 2; }

# --- before snapshots -------------------------------------------------------
snapshot() {
    local name="$1"; shift
    if "$@" >"$WORKDIR/$name.$2" 2>/dev/null; then :; else echo "(unavailable)" >"$WORKDIR/$name.$2"; fi
}
before_snapshots() {
    local phase="$1"
    if command -v dpkg-query >/dev/null; then
        dpkg-query -W >"$WORKDIR/packages.$phase" 2>/dev/null || echo na >"$WORKDIR/packages.$phase"
    else
        echo na >"$WORKDIR/packages.$phase"
    fi
    if command -v systemctl >/dev/null; then
        systemctl list-unit-files --no-pager --plain >"$WORKDIR/units.$phase" 2>/dev/null || echo na >"$WORKDIR/units.$phase"
    else
        echo na >"$WORKDIR/units.$phase"
    fi
    crontab -l >"$WORKDIR/cron.$phase" 2>/dev/null || echo na >"$WORKDIR/cron.$phase"
}

before_snapshots before
MARKER="$WORKDIR/marker"
touch "$MARKER"
sleep 1

# --- the run -----------------------------------------------------------------
python3 "$INVENTORY_DIR/atlas_inventory.py" run --output-dir "$OUTDIR"
RC=$?
if [ "$RC" -eq 0 ] || [ "$RC" -eq 3 ]; then
    pass "run exit code $RC (0=complete, 3=partial)"
else
    fail "run exit code $RC (expected 0 or 3)"
fi

# --- after snapshots + read-only assertions ----------------------------------
before_snapshots after
for pair in packages units cron; do
    if diff -q "$WORKDIR/$pair.before" "$WORKDIR/$pair.after" >/dev/null; then
        pass "$pair unchanged"
    else
        fail "$pair changed during inventory run"
    fi
done

# No file outside the output dir modified since the marker (in dirs we probe).
CHANGED=$(find /etc /opt /srv /var/spool/cron -newer "$MARKER" -type f 2>/dev/null | head -20)
if [ -z "$CHANGED" ]; then
    pass "no files modified in /etc /opt /srv /var/spool/cron"
else
    fail "files modified during run: $CHANGED"
fi

# --- output assertions --------------------------------------------------------
REPORT=$(ls "$OUTDIR"/report-*.json 2>/dev/null | head -1)
AUDIT=$(ls "$OUTDIR"/audit-*.json 2>/dev/null | head -1)
WORKSHEET=$(ls "$OUTDIR"/classification-worksheet-*.md 2>/dev/null | head -1)
[ -n "$REPORT" ] && pass "report written" || fail "report missing"
[ -n "$AUDIT" ] && pass "audit written" || fail "audit missing"
[ -n "$WORKSHEET" ] && pass "worksheet written" || fail "worksheet missing"

if [ -n "$REPORT" ]; then
    for f in "$REPORT" "$AUDIT"; do
        MODE=$(stat -c %a "$f")
        [ "$MODE" = "600" ] && pass "$(basename "$f") mode 600" || fail "$(basename "$f") mode $MODE (expected 600)"
    done

    python3 - "$REPORT" "$INVENTORY_DIR" <<'PYEOF'
import json, sys
report_path, inventory_dir = sys.argv[1], sys.argv[2]
sys.path.insert(0, inventory_dir)
import atlas_inventory as ai

report = json.load(open(report_path))
errors = ai.schema_validate(report, ai.REPORT_SCHEMA)
assert not errors, "schema validation failed: %s" % errors[:10]
print("ok:   report validates against schema v%d" % ai.SCHEMA_VERSION)

missing = set(ai.CATEGORIES) - set(report["categories"])
assert not missing, "missing categories: %s" % missing
print("ok:   all %d ATLAS-ENV-001 categories present" % len(ai.CATEGORIES))

statuses = {}
for cat in report["categories"].values():
    for item in cat["items"].values():
        assert item["status"] in ai.ALL_STATUSES, item
        statuses[item["status"]] = statuses.get(item["status"], 0) + 1
print("ok:   explicit statuses on every item: %s" % statuses)
assert report["run"]["privileged"] is False, "test must run unprivileged"
print("ok:   ran unprivileged")
PYEOF
    [ $? -eq 0 ] || fail "report content assertions failed"
fi

echo
if [ "$FAILURES" -eq 0 ]; then
    echo "INTEGRATION TEST PASSED ($WORKDIR)"
    exit 0
else
    echo "INTEGRATION TEST FAILED: $FAILURES failure(s) ($WORKDIR)"
    exit 1
fi
