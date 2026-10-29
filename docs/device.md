# The target device

Atlas runs on one Raspberry Pi. This page records how it is laid out. Network
addresses, firewall rules and access details are kept out of the public
repository.

## Hardware and OS

Raspberry Pi 5 Model B, 16 GB RAM, 256 GB NVMe, Debian 13 (trixie). The
acceptance environment is the Pi itself. Tests run off-device; the suites need
only Python and `git`.

## Deployment

- The repository is cloned in the `atlas` directory of the `pi` user's home
  and kept current with `git pull`. This is the live working tree. No files
  are copied across.
- Scheduled work runs as user-level systemd units in
  `.config/systemd/user/` with linger on: `atlas-repotrack-update`,
  `atlas-poll-chain-head`, `atlas-probe`, `atlas-upgrade`, `atlas-fleet`, and
  the masked `atlas-subnt`. Only `atlas-dashboard.service` is a system unit.
  The unit files live in each component's `systemd/` directory. The README
  schedule table is generated from them.
- Privileged steps need a password and are run by the operator. Automation
  never enters one.

## Hermes

Hermes runs as user `pi`, started by hand (there is no service unit yet).
Memory and skill writes are approval-gated. Atlas registers four read-only
stdio MCP servers with it:

| Server | Entry point | Serves |
|---|---|---|
| `atlas-kb` | `knowledge/atlas_kb_server.py` | The validated corpus |
| `atlas-repo` | `repotrack/atlas_repo_server.py` | Subtensor source evidence |
| `atlas-live` | `livedata/atlas_live_server.py` | Current provider data |
| `atlas-fleet` | `fleet/atlas_fleet_server.py` | Fleet search, rotation metrics, mining screen |

## Stores

All stores are device-local, gitignored and live under `var/`:
`var/knowledge/`, `var/repotrack/`, `var/livedata/`, `var/telegram/` and
`var/fleet/` (clones, `fleet.db`, `www/`). Secrets live only in the 0600
`.env`; see [`env.example`](../env.example).

Dated acceptance records for every phase are in
[`decisions.md`](decisions.md).
