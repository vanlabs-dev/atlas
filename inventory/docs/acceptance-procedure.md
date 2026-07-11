# First real inventory run on the Pi — acceptance procedure

**Change:** `atlas-phase-0-device-inventory`, task 6.3
**Who:** the operator (you), on the target Raspberry Pi
**When:** whenever you're ready — this run is the Phase 0 evidence step and is
**not** automated by any tooling in this repo. Nothing in this repo can reach
the Pi.

This is the acceptance step for the change: the implementation is complete and
tested off-device (unit suite + WSL integration run); executing it on the Pi
and reviewing the outputs is the operator's decision and action.

## 1. Transfer the script (current method: git pull)

The repo is cloned on the Pi (user `pi`, access via SSH), so:

1. SSH into the Pi as `pi` (non-root).
2. In the repo checkout: `git pull` — git guarantees content integrity.
3. Confirm Python is available: `python3 --version` (needs 3.9+, stdlib only).

> Historical note: the original transfer plan was pasting the single file over
> SSH with a `sha256sum` check; git supersedes it, but the script remains
> self-contained so that fallback still works.

## 2. Run unprivileged

```sh
cd <repo-checkout>
python3 inventory/atlas_inventory.py run --output-dir var/inventory
```

- Do **not** use sudo for the first run. The script never self-elevates.
- Expect exit code `0` (complete) or `3` (partial). Partial is normal
  unprivileged — firewall rules and `/root` typically need privilege.
- Outputs (all mode 0600, owned by you) in `var/inventory/` under the checkout:
  - `report-<run-id>.json`
  - `classification-worksheet-<run-id>.md`
  - `audit-<run-id>.json`

## 3. Manually scan the report before storing or sharing it

The redaction filter is defense-in-depth, not a substitute for your eyes.
Before the report leaves the Pi or gets archived:

```sh
less var/inventory/report-<run-id>.json
```

- Search for anything that looks like a key, token, or password
  (`/key`, `/token`, `/pass` in `less`). If you find a real secret value,
  do not store or share the report — note the leaking field and report it as
  a bug against the redaction filter.
- Check the `secret_file_locations` section contains **paths and metadata
  only**, never contents.

## 4. Review the classification worksheet

Open `classification-worksheet-<run-id>.md` and resolve every row:

- Every `decision required` row needs your answer (keep / migrate / remove)
  before Phase 1 planning.
- Any `remove` proposal is only a proposal — actual removal happens in the
  separate ATLAS-ENV-002 change after you approve a removal plan.
- The worksheet also answers several PRD §21 blocking questions (Pi model,
  OS/kernel, what exists to preserve) — record those answers.

## 5. Decide on a privileged re-run (optional)

If the unprivileged report shows `permission-denied` items you care about
(firewall rules, NVMe SMART health, `/root` contents), you may re-run with
sudo. That is your explicit choice; review the probe table
(`docs/probe-review.md`) first — every command is read-only.

```sh
sudo python3 atlas_inventory.py run --output-dir var/inventory
```

## 6. Storage

- Keep reports in `var/inventory/` under the checkout for now. This location
  is provisional: the backup change (ATLAS-BACKUP-001) will decide whether and
  how inventory artifacts are included in backups.
- Do not commit reports to the repo and do not paste them into chats or
  issues — they describe your device in detail (users, ports, versions).
  `var/` is in the repo's `.gitignore` as a safeguard, since the Pi checkout
  is itself the git working tree.

## 7. Acceptance checklist

- [ ] Checksums matched after transfer
- [ ] Run completed with exit 0 or 3; audit record present
- [ ] Manual secret scan of the report found nothing sensitive
- [ ] `secret_file_locations` contains paths/metadata only
- [ ] Worksheet reviewed; every `decision required` row resolved or queued
- [ ] Report + worksheet + audit stored in `var/inventory/`
- [ ] PRD §21 answers informed by the report are recorded

When all boxes are ticked, the ATLAS-ENV-001 scenario evidence exists and the
change can be archived; the removal plan (ATLAS-ENV-002) and hardening
assessment (ATLAS-ENV-003) changes can then consume this report.
