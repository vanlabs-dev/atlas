#!/usr/bin/env bash
# Reinstall atlas-repotrack-update.service from the repo (includes poll-chain-head).
# Run: sudo ./repotrack/scripts/install-repotrack-unit.sh [--poll-now]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/repotrack/systemd/atlas-repotrack-update.service"
DST=/etc/systemd/system/atlas-repotrack-update.service
if [[ ! -f "$SRC" ]]; then
  echo "missing $SRC" >&2
  exit 1
fi
cp "$SRC" "$DST"
systemctl daemon-reload
echo "installed $DST"
systemctl cat atlas-repotrack-update.service | grep -E 'ExecStart' || true
if [[ "${1:-}" == "--poll-now" ]]; then
  # Prefer the calling user for network/env; if root, drop to pi when present.
  if [[ "$(id -u)" -eq 0 ]] && id pi >/dev/null 2>&1; then
    sudo -u pi python3 "$ROOT/livedata/atlas_live.py" poll-chain-head
  else
    python3 "$ROOT/livedata/atlas_live.py" poll-chain-head
  fi
fi
