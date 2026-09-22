# Finalized mainnet upgrade maintenance

## Status and authority

The operator approved scoped implementation, isolated Pi testing, ordinary
Atlas-only publication, and validated code/knowledge activation on 2026-09-22.
This is not permission to weaken remote branch rules or host security.
`config.json` ships with publication and activation disabled. Do not enable
those switches merely because component tests pass.

The integration adds `maintenance/` without extending the dated corpus's
accepted runtime coverage. The initial scan anchor is an explicit historical
pin, not a declaration that every older deployment has a machine audit.
Completion requires the real upgrade-cycle acceptance described below.

## Trust boundaries

- The deterministic controller owns RPC reads, private SQLite state, receipts,
  Git transport, and deployment. The worker receives no signing or deploy key.
- A pinned, tool-free Hermes inference process returns hash-bound text edits.
  File requests are limited to allowed tracked text. New regular files are
  explicit. Upstream source and model output cannot issue host commands.
- Candidate tests run in networkless bubblewrap namespaces with a read-only
  candidate and dedicated dependencies. Host home, `.git`, `.env`, and runtime
  stores are hidden. CPU, memory, processes, descriptors, output, and wall time
  are bounded; user services add aggregate resource bounds. The mandatory
  runner uses a trusted launcher outside the candidate, disables candidate
  test configuration, and requires a completed test-session receipt. Automatic
  candidates cannot change the test harness. These checks reject early-exit
  and stdout-only success reports; they do not cryptographically prove
  arbitrary Python executed honestly inside its interpreter. Independent
  source review remains mandatory.
- A fresh reviewer checks the exact candidate manifest and evidence. A trusted
  report is part of that manifest, not an unreviewed addition after approval.
- Publication binds a signed receipt to the exact baseline, candidate tree,
  evidence, review, and checks. Its authenticated journal records the intended
  commit before push. Recovery reconciles that exact remote commit rather than
  generating another one. No force pushes or branch-rule bypasses exist.
- Maintenance policy, its code, credentials, and reader-control installation
  are outside the automatic coding worker's permitted changes. Updating this
  control plane requires a separate operator-reviewed change.

## Detection and source evidence

The independent scanner checks finalized headers in deployment order. A runtime
update digest triggers pinned parent/current reads, including runtime versions,
metadata, and code hashes. Same-spec replacements and rollbacks remain distinct
jobs. Cursor advancement and accepted records commit transactionally. Missing
archive state, malformed responses, wrong genesis, and ancestry disagreement
block scanning without jumping ahead.

The configured archive endpoint supports historical code reads. Batch sizes
respect its observed request policy. The ordinary live endpoint's ability to
answer an old runtime-version request does not prove that it retains old code.

Source mapping verifies official GitHub release asset identities and digests,
manifest/source declarations, the local source commit, and equivalence with
pinned deployed WASM. This is **publisher-declared build provenance**, not an
independent reproducible-build attestation. A raw dictionary or matching tag
alone is not accepted as provenance.

Packets retain all changed paths, full binary source diffs, metadata, and
checksums. Model input includes every source chunk and a lossless projection
of changed metadata nodes; unchanged metadata is not repeated in the prompt.
Full decoded metadata remains in the private evidence directory. A request
that exceeds the model budget blocks; it never silently drops evidence.

Historical bundles retain every intervening transition, including changes
later reverted. Historical audit completion is distinct from current-code
activation. A newer runtime invalidates a stale publication/activation attempt.

## Tests and verification

Create the dedicated test environment with the pinned requirements:

```sh
python3 -m venv /home/pi/.cache/atlas-maintenance-venv
/home/pi/.cache/atlas-maintenance-venv/bin/pip install -r maintenance/requirements.lock
```

Use `maintenance.sandbox.run_tests(repo)` for the full isolated run. It executes
pytest separately for inventory, hardening, Hermes integration, knowledge,
repo tracking, livedata, Telegram, fleet, subnt (`subnt/tests`), and maintenance. Missing,
failed, skipped, or deselected mandatory tests block success. Results preserve
per-suite counts and bounded logs; a successful shell exit alone is insufficient.

Required verification also includes explicit MCP contract tests, pinned storage
reads interpreted using metadata/defaults, evidence-selected migration and
governance proof, staged knowledge validation, and live acceptance after
activation. A runtime hash freshness check is not proof of migration completion.
An unset storage value is not proof of a removed storage item.

## CLI and state

Run from the installed Atlas checkout using the dedicated Python:

```sh
/home/pi/.cache/atlas-maintenance-venv/bin/python -m maintenance.atlas_maintenance status
/home/pi/.cache/atlas-maintenance-venv/bin/python -m maintenance.atlas_maintenance init
/home/pi/.cache/atlas-maintenance-venv/bin/python -m maintenance.atlas_maintenance scan
/home/pi/.cache/atlas-maintenance-venv/bin/python -m maintenance.atlas_maintenance process
```

`init` uses the explicit configured historical anchor; it cannot silently reset
an existing ledger. Do not delete the database to clear a blocked job. Private
state lives under `var/maintenance/`: deployment jobs, evidence, candidates,
validation/publication journals, deployment receipts, and notifications.

The scanner and worker have separate process locks. State transitions, leases,
attempt counts, retry times, and stage receipts are durable. Recovery preserves
completed gates. Notification enqueue failure cannot downgrade an activated
job. Telegram delivery uses bounded durable retries and successful-delivery
deduplication; it does not claim network-level exactly-once delivery.

## One-time installation boundary

Do not activate this installation until integrated acceptance passes. The
following is the reviewed migration shape, not a claim it has run on the Pi.

1. Preserve the clean live checkout and its exact accepted commit.
2. Publish the reviewed implementation through the approved repository.
3. Outside the active chat, pause the existing Atlas tool-server clients using
   their supported lifecycle. Never stop the active gateway from its own tool.
4. Disable the system-owned producer timers with operator authentication:

```sh
sudo systemctl disable --now atlas-repotrack-update.timer atlas-fleet.timer atlas-subnt.timer
```

5. Wait for existing producer services to become inactive. Do not kill a job
   writing a database. Bring the clean live checkout to the reviewed commit.
6. Prepare equivalent inactive user units and inert reader-control files:

```sh
python3 -m maintenance.install prepare
python3 -m maintenance.install prepare-readers
```

`prepare-readers` installs the small trusted controller outside the mutable
checkout and prints `hermes config set` commands. It changes no Hermes settings.
It refuses to overwrite different operator files. Its private reader config
starts with `managed_launches_only: false`.

7. Apply the printed commands through the Hermes CLI, preserving all existing
   per-server environment settings. The four Atlas servers are knowledge,
   repo tracking, livedata, and fleet; fleet also hosts mining tools.
8. Only after all Atlas launches are managed, explicitly attest that policy in
   the private reader config. Bootstrap the reader gate while old unmanaged
   server processes are absent. Restart clients through their supported
   lifecycle, then verify a fresh tool handshake for every Atlas server.
9. Verify the reader pause/check/reload/resume cycle and producer quiescence.
   `maintenance.install enable` refuses active/enabled system timers or active
   producer jobs and reads back user timer enablement/activity after installation.
10. Enable publication/activation only after the real acceptance gate passes.
    Keep the controller policy and reader configuration outside worker writes.

No sudo password is stored. No broad passwordless sudo or security exception is
required. Keep the legacy user `atlas-poll-chain-head.timer` disabled and its
service inactive; the deployment gate refuses an enabled timer, running service,
or pending job outside the migrated producer set. The static `atlas-dashboard`
service serves only rendered files under `var/fleet/www` and loads no Atlas code;
it does not require a code-reader restart.

The system-timer migration and old client lifecycle are operator
prerequisites, not conditions the agent may assume away.

The public publisher was renamed to subnt before this maintenance installation.
Use `subnt/atlas_subnt.py` and `atlas-subnt.service`/`atlas-subnt.timer`, not the
retired publisher paths or units. Preparing user units preserves the current
renderer command, scheduling, and resource settings; it removes only system
identity directives. The renderer remains protected from automatic candidate
edits, and its contract suite remains mandatory. This installation does not
repeat the completed publisher checkout/state migration.

## Reader and deployment safety

The trusted reader wrapper serializes new launches with a durable pause marker.
Each server holds a shared lifetime lock. Wrappers can signal only their own
pidfd-bound child, never gateway parents or arbitrary registry PIDs. Unmanaged
or orphaned readers block deployment. Fresh MCP readiness probes run while
public launches remain paused. Client reconnection must also be verified.

Deployment requires exact local/remote identities, producer and reader
quiescence, SQLite backups through the backup API, and the previous active
knowledge run. Stage and validate the new corpus before activation. Recheck
runtime freshness inside the maintenance window. Resume only after accepted
activation or verified rollback, never in an unconditional cleanup handler.

A failed activation restores the prior local release and knowledge run only
when external changes do not conflict. A remote validated commit remains in
history; any remote correction is a new reviewed commit. Never overwrite newer
operator work to make a recovery test pass.

## Completion gate

Before calling the system operational, retain receipts for:

- The complete historical scan range and every intervening deployment.
- The initial accepted baseline's actual audit scope.
- A real historical source-review replay, clearly marked historical.
- All mandatory isolated tests and independent exact-tree review.
- One approved real cycle through publication, remote readback, local rollout,
  knowledge activation, and live tool/notification/public-output acceptance.
- Supervised restart recovery and a repeated unchanged-chain poll that creates
  neither another commit nor another successful-delivery notification.

A blocked job is a valid safety outcome, not a completed upgrade. Inspect its
saved gate receipt before retrying. Fix missing evidence or permissions rather
than changing a success flag.
