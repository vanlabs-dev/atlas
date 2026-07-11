# Atlas Hermes baseline verification (Phase 1)

Read-only post-install verification of a **manually installed** Hermes, per
PRD requirements **ATLAS-HERMES-001/002/005** via OpenSpec change
`atlas-phase-1-hermes-baseline`.

## What it does — and does not do

- **Verifies, never installs**: the operator performs the Hermes install and
  interactive setup by hand ([docs/manual-install-notes.md](docs/manual-install-notes.md));
  this tool only checks the result.
- **Read-only, always**: no service is started, stopped, restarted, enabled,
  or disabled; no configuration is written. The only writes are redacted
  0600 reports in gitignored `var/hermes/`.
- **Fails closed**: a missing/incomplete install record yields *no verdict*;
  any finding, unresolved unknown (`permission-denied`,
  `unsupported-on-device`, `unknown`), or missing attestation yields
  **not-accepted** with every blocker named. Deviations are only non-blocking
  when the install record carries a documented `exceptions` entry — which the
  report reproduces, so nothing is silently waived.
- Reuses the inventory tool's reviewed probe/redaction/schema machinery
  (pinned by `tests/test_import_surface.py`) — one implementation of
  "read-only probe" in this repo.

## The checks

| check | what it verifies |
|---|---|
| `install-record` | all 8 ATLAS-HERMES-001 fields recorded |
| `unprivileged-execution` | runs as the recorded non-root user; no sudo-capable group membership or sudoers grants (ATLAS-HERMES-002) |
| `telemetry-disabled` | config/.env explicitly disable telemetry (decision Q11) |
| `diagnostics` | the recorded official diagnostics command exits clean |
| `service-persistence` | unit loaded/enabled/active; restart evidenced by start timestamp — evidence only, the verifier never restarts |
| `secret-free-logs` | no credential-shaped material in Hermes logs/journal (excerpts always redacted) |

**Interactive checks are attested, not automated.** Basic chat, memory write
+ cross-session search, and discovering/calling the test tool are things only
a real Hermes session can show. You perform them, then pass `--attest` for
each; the report records who attested what, when. An unattested check blocks
acceptance — the verifier never marks it passed on its own.

## Usage

```sh
# on the Pi, from the repo root, after completing
# var/hermes/install-record.json and the interactive checks:
python3 hermes/atlas_hermes_verify.py verify \
    --attest chat --attest memory-session-search --attest tool-call
```

Run unprivileged first. If journal or sudoers checks report
`permission-denied`, either record an exception or re-run under `sudo` per
the operational note in [docs/decisions.md](../docs/decisions.md) (root-owned
outputs follow).

Exit codes: `0` accepted · `3` not-accepted (blockers listed) · `4` no
verdict (install record missing/incomplete) · `1` fatal.

Outputs per run: `verification-<run id>.json` (schema-validated),
`summary-<run id>.md` (for the decision log), `audit-<run id>.json`.

## The test tool

[`testtool/atlas_test_tool.py`](testtool/atlas_test_tool.py) is a deliberately
inert stdio MCP server with exactly one tool, `atlas_ping`, returning static
identity data. It exists solely to prove the Hermes↔Atlas local tool path
(ATLAS-HERMES-005) and has **no data access**: no filesystem reads, no
network, no subprocess (enforced by `tests/test_testtool.py`). Register it in
Hermes as a local stdio MCP server:

```yaml
# shape depends on Hermes config; conceptually:
command: python3
args: ["/home/pi/atlas/hermes/testtool/atlas_test_tool.py"]
```

It will be **replaced** (not extended) by the production Atlas tool
interface in a later phase.

## Related module

[`memory/`](memory/README.md) verifies Hermes memory and session recall
behavior (ATLAS-MEM-001…006) after this baseline is accepted — same
read-only, fail-closed, attestation-based approach, reusing this
verifier's record/check/verdict machinery.

## Tests

```sh
cd hermes/tests && python3 -m unittest discover -v
```

Off-device only (WSL/dev machine); the Pi run after the operator's install is
the acceptance run.
