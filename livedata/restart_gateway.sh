#!/usr/bin/env bash
# Restart Hermes gateway from a shell OUTSIDE the gateway process tree.
# Safe to run over SSH on the Pi:
#   bash ~/atlas/livedata/restart_gateway.sh
set -euo pipefail
echo "Restarting hermes-gateway..."
if command -v hermes >/dev/null 2>&1; then
  hermes gateway restart || systemctl --user restart hermes-gateway
else
  systemctl --user restart hermes-gateway
fi
sleep 2
systemctl --user --no-pager status hermes-gateway | head -20
echo
echo "Expected atlas-live tools after restart:"
echo "  live_burn_leaderboard, live_chain_head, live_metagraph,"
echo "  live_network_stats, live_portfolio, live_price, live_status, live_subnets"
