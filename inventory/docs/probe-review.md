# Probe table read-only review

**Change:** `atlas-phase-0-device-inventory`, task 6.2
**Reviewed:** 2026-07-11, against `atlas_inventory.py` script version 0.1.0
**Method:** every entry below was generated from the live `PROBES` table
(`python -c "...print(p.display_command())..."`), then each command was reviewed
for mutating flags/subcommands. A unit test (`test_probes.ProbeTableTests`)
additionally asserts every probe belongs to a declared category, every declared
parser exists, and no cmd argv contains shell metacharacters.

**Execution guarantees reviewed alongside the commands:**

- All `cmd` probes run as argv lists with `subprocess.run` — no shell, no
  interpolation. No command is ever constructed from collected data; paths
  discovered at runtime go only to `os.lstat()`/`os.stat()` syscalls.
- `read` probes open files read-only (`open(path, "rb")`), capped at 64 KB.
- `stat-glob` probes call `os.lstat()` only — contents are never read
  (this is how secret-file locations are recorded without exposure).
- `which` probes call `shutil.which()` — a PATH search, no execution.
- The script contains no call to `sudo`, no privilege elevation, and no probe
  executes a discovered binary (Hermes version comes from metadata files only).

## Review verdicts

| # | Item | Kind | Command | Read-only verdict |
|---|---|---|---|---|
| 1 | hardware.model | read | `/proc/device-tree/model`, `/sys/firmware/devicetree/base/model` | ✅ procfs/sysfs read |
| 2 | hardware.architecture | cmd | `uname -m` | ✅ pure query; uname has no mutating mode |
| 3 | cpu_memory_storage.cpu | cmd | `lscpu` | ✅ pure query |
| 4 | cpu_memory_storage.memory | read | `/proc/meminfo` | ✅ procfs read |
| 5 | cpu_memory_storage.block_devices | cmd | `lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,MODEL` | ✅ `-J`/`-o` are output-format flags; lsblk never writes |
| 6 | cpu_memory_storage.filesystem_usage | cmd | `df -P -k` | ✅ pure query; `-P -k` are format flags |
| 7 | cpu_memory_storage.partitions | read | `/proc/partitions` | ✅ procfs read |
| 8 | os_kernel.os_release | read | `/etc/os-release` | ✅ file read |
| 9 | os_kernel.kernel | cmd | `uname -a` | ✅ pure query |
| 10 | users_and_service_accounts.passwd_users | read | `/etc/passwd` | ✅ world-readable by design; `/etc/shadow` is never touched |
| 11 | packages.dpkg_packages | cmd | `dpkg-query -W -f '${Package}\t${Version}\n'` | ✅ `dpkg-query` is the read-only query frontend (unlike `dpkg`) |
| 12 | packages.rpm_packages | cmd | `rpm -qa --qf ...` | ✅ `-q` is query mode; no install/erase flags |
| 13 | containers.docker_containers | cmd | `docker ps -a --format '{{json .}}'` | ✅ `ps` lists only |
| 14 | containers.docker_images | cmd | `docker images --format '{{json .}}'` | ✅ lists only |
| 15 | containers.podman_containers | cmd | `podman ps -a --format json` | ✅ lists only |
| 16 | systemd_services.service_units | cmd | `systemctl list-units --type=service --all --no-pager --plain --no-legend` | ✅ `list-*` verbs are read-only; no start/stop/enable |
| 17 | systemd_services.service_unit_files | cmd | `systemctl list-unit-files --type=service --no-pager --plain --no-legend` | ✅ read-only verb |
| 18 | listening_ports.sockets | cmd | `ss -tulnp` | ✅ socket dump; `-p` may be privilege-limited, still read-only |
| 19 | scheduled_jobs.user_crontab | cmd | `crontab -l` | ✅ `-l` lists; `-r`/`-e` (mutating) absent |
| 20 | scheduled_jobs.system_crontab | read | `/etc/crontab` | ✅ file read |
| 21 | scheduled_jobs.cron_directories | stat-glob | `/etc/cron.d/*` etc. | ✅ lstat only |
| 22 | scheduled_jobs.systemd_timers | cmd | `systemctl list-timers --all --no-pager --plain --no-legend` | ✅ read-only verb |
| 23 | hermes_installation.hermes_files | stat-glob | `~/.hermes*`, `/opt/hermes*`, `/usr/local/hermes*`, bins, units | ✅ lstat only; binaries never executed |
| 24 | hermes_installation.hermes_version_files | read | candidate `VERSION` metadata files | ✅ file read, `missing_ok`; version never obtained by running a binary |
| 25 | repositories_and_app_dirs.git_repositories | cmd | `find /home /opt /srv /root /usr/local -maxdepth 4 -name .git -type d` | ✅ no `-delete`/`-exec`; prints paths only |
| 26 | repositories_and_app_dirs.application_directories | stat-glob | `/opt/*`, `/srv/*` | ✅ lstat only |
| 27 | secret_file_locations.secret_files | cmd | `find ... ( -name .env* -o ... ) -type f` | ✅ no `-delete`/`-exec`; results are lstat'ed, contents never read |
| 28 | backup_configuration.backup_tools | which | restic, borg, rsnapshot, timeshift, rclone, duplicity | ✅ PATH lookup only |
| 29 | backup_configuration.backup_configs | stat-glob | `/etc/restic*` etc. | ✅ lstat only |
| 30 | firewall.ufw_status | cmd | `ufw status verbose` | ✅ `status` is read-only (vs `enable`/`allow`) |
| 31 | firewall.nftables_ruleset | cmd | `nft list ruleset` | ✅ `list` is read-only (vs `add`/`flush`) |
| 32 | firewall.iptables_rules | cmd | `iptables -S` | ✅ `-S` prints rules (vs `-A`/`-D`/`-F`) |
| 33 | remote_access.sshd_config | read | `/etc/ssh/sshd_config` | ✅ config read; contains directives, no key material |
| 34 | remote_access.vpn_tools | which | tailscale, wg, zerotier-cli, openvpn | ✅ PATH lookup only |
| 35 | device_health.thermal_zones | read | `/sys/class/thermal/thermal_zone*/temp` | ✅ sysfs read |
| 36 | device_health.vcgencmd_temperature | cmd | `vcgencmd measure_temp` | ✅ `measure_temp` reads firmware telemetry; no `set_*` subcommand used |
| 37 | device_health.nvme_smart | cmd | `smartctl -H -j /dev/nvme0` | ✅ `-H` reads SMART health; no self-test is started (`-t` absent) |
| 38 | device_health.uptime_load | read | `/proc/uptime`, `/proc/loadavg` | ✅ procfs read |

## Verdict

All 38 probes are read-only. No mutating flags or subcommands are present.
Any future probe addition must be re-reviewed here and keep
`test_probes.ProbeTableTests` passing.
