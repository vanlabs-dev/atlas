# Fleet Rotation Metrics

## Why

The fleet already records what changed (change ranges, terms, events) but nothing
answers the operator's actual rotation question: "across all ~130 subnets, which
deserve capital and which should be faded — and why, with evidence?" A one-shot
on-device sweep (2026-07-19) validated that the clones hold differentiated,
uncompiled signal: hardcoded emission routing (netuid 54 sends 35% of emissions
to a partner hotkey in live reward code; ~60 subnets carry burn mechanics, 17
partner/royalty splits), and repo-activity staleness — but also proved the naive
versions are wrong (default-branch staleness flags chutes/computehorde as dead;
raw commit counts inherit fork history). This change turns the validated sweep
into standing metrics plus a LAN-only dashboard, phased so usable data ships
from the first pass.

## What Changes

- New metrics module over the existing fleet store and clones, read-only,
  never executing subnet code, per-subnet fail-closed:
  - **Emission-redirect map**: per (netuid, epoch), routing entries
    (kind: burn/partner/treasury/owner/royalty; fraction where parseable;
    destination hotkey where present) extracted from reward/weight/scoring
    code paths with file:line evidence, plus derived miner-take; subnets whose
    economics load from a remote URL at runtime are flagged `opaque` instead
    of guessed.
  - **Repo-activity metric**: epoch-scoped commit velocity and author counts
    (windowed, default-branch), plus a cheap **branch pulse** — per-pass
    `git ls-remote --heads` tip snapshot; count of changed tips between passes
    approximates off-default-branch activity without fetching or dating.
  - **Team-concentration map**: GitHub org per slot; orgs running multiple
    subnets surfaced as correlated-fate groups (placeholder orgs excluded).
- **Quadrant screen**: repo activity × alpha-price momentum computed from the
  already-accumulating `signal_prices` vectors; renders with whatever price
  window exists (momentum columns appear as history accrues, never fabricated).
- **Static dashboard**: one self-contained HTML file rendered into `var/fleet/`
  at the end of the hourly fleet pass (ranked table, quadrant, emission map with
  evidence, invisible-fleet tier listing no-repo/unreachable/placeholder-URL
  slots as opaque), served LAN-only by a minimal systemd http unit on the Pi.
- Fleet reconcile pass additionally records branch head tips per slot
  (one `ls-remote` per active slot per pass; no clone/fetch cost).
- All metrics available as CLI/JSON reports before and independent of the
  dashboard (data ships first; the page is a renderer).

## Capabilities

### New Capabilities

- `fleet-rotation-metrics`: emission-redirect map, epoch-scoped repo-activity
  with branch pulse, team-concentration map, quadrant computation, CLI/JSON
  reports, and the static LAN dashboard render + serve.

### Modified Capabilities

- `subnet-repo-fleet`: reconcile pass records a per-slot branch-tips snapshot
  (`ls-remote --heads`) alongside the existing update flow, fail-closed per
  slot, so branch pulse can be derived without fetching branch history.

## Impact

- **Code**: new `fleet/atlas_fleet_metrics.py` (extraction, scoring, render) +
  small hook in the fleet pass (branch tips + render step); one new systemd
  unit (`atlas-dashboard.service`, static file server bound to LAN). Existing
  reconcile/signals/index code paths untouched except the pass hook.
- **Store**: additive tables only (`metric_emission_routes`, `metric_activity`,
  `metric_branch_tips`, plus render state); existing schemas unmodified.
- **Runtime cost**: one `ls-remote` per active slot per pass (~104 cheap git
  calls, no blobs), regex/diff extraction over already-local files, one HTML
  render. No new external APIs, no new quota use (price momentum reuses stored
  `signal_prices`).
- **Security posture unchanged**: read-only over untrusted clones, nothing
  executed, dashboard bound to LAN only, no secrets in the page.
- **Known operational constraints** (from the validated sweep): tooling must
  bypass gitignore when scanning clones (`rg --no-ignore` + explicit path);
  no `sqlite3` binary on the Pi (Python stdlib only); metrics must be
  epoch-scoped to survive slot re-points.
