# Supplementary probe read-only review

**Change:** `atlas-phase-0-hardening-assessment`, task 5.2
**Reviewed:** 2026-07-11, against `atlas_hardening.py` version 0.1.0
**Scope:** only the probes this module adds. The 38 inventory probes are
reviewed in [`inventory/docs/probe-review.md`](../../inventory/docs/probe-review.md);
this module executes them only indirectly by *reading* inventory reports.

All probes below run through the inventory tool's reviewed machinery
(`inv.run_probe`): argv execution without a shell, redaction before storage,
explicit status envelopes, no self-elevation, no commands built from
collected data. `test_import_surface.py` asserts their parsers exist and the
area/evaluator tables stay total.

| # | Item | Kind | Command | Read-only verdict |
|---|---|---|---|---|
| 1 | time_sync | cmd | `timedatectl show --property=NTP,NTPSynchronized,Timezone` | ✅ `show` prints properties; the mutating verbs (`set-ntp`, `set-time`) are absent |
| 2 | auto_upgrades_config | read | `/etc/apt/apt.conf.d/20auto-upgrades`, `.../50unattended-upgrades` | ✅ config file read (`missing_ok`); contains no secrets |
| 3 | var_log_perms | stat-glob | `/var/log`, `/var/log/*` | ✅ lstat only — log *contents* are never read |
| 4 | sshd_restart_policy | cmd | `systemctl show ssh.service -p Restart --no-pager` | ✅ `show` prints unit properties; no start/stop/edit verbs |

## Verdict

All 4 supplementary probes are read-only. The assessor additionally contains
no code path that executes plan commands — plan rendering is pure string
construction (verified by the integration test's before/after state snapshot).
Any future probe addition must be re-reviewed here.
