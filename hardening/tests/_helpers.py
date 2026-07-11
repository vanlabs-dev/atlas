"""Test helpers: imports, fixture builders for inventory reports and probes."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import atlas_hardening as ah  # noqa: E402

inv = ah.inv


def envelope(status="collected", command="test", data=None, **extra):
    env = {"status": status, "command": command, "duration_ms": 0.0}
    if data is not None:
        env["data"] = data
    env.update(extra)
    return env


def base_inventory(item_overrides=None, run_overrides=None):
    """Schema-valid inventory report; overrides: {category: {item: envelope}}."""
    categories = {name: {"items": {}} for name in inv.CATEGORIES}
    for category, items in (item_overrides or {}).items():
        categories[category]["items"].update(items)
    run = {
        "run_id": "20260711T062206Z-5be02d8f",
        "script_version": inv.SCRIPT_VERSION,
        "schema_version": inv.SCHEMA_VERSION,
        "started_at": "2026-07-11T06:22:06+00:00",
        "finished_at": "2026-07-11T06:22:11+00:00",
        "executing_account": "pi",
        "hostname": "raspberrypi",
        "privileged": False,
        "complete": True,
    }
    run.update(run_overrides or {})
    return {"run": run, "categories": categories}


# --- the real Pi clean baseline, as observed on 2026-07-11 -------------------

PI_SOCKET_LINES = [
    "Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:PortProcess",
    "udp   UNCONN 0      0            0.0.0.0:5353       0.0.0.0:*",
    "udp   UNCONN 0      0                  *:5353             *:*",
    "tcp   LISTEN 0      4096         0.0.0.0:111        0.0.0.0:*",
    "tcp   LISTEN 0      128          0.0.0.0:22         0.0.0.0:*",
    "tcp   LISTEN 0      128             [::]:22            [::]:*",
]


def pi_baseline_inventory():
    return base_inventory({
        "remote_access": {
            "sshd_config": envelope(data={
                "directives": {
                    "kbdinteractiveauthentication": ["no"],
                    "x11forwarding": ["yes"],
                },
                "note": "selected directives only",
            }),
        },
        "listening_ports": {
            "sockets": envelope(data={"text_lines": PI_SOCKET_LINES}),
        },
        "firewall": {
            "ufw_status": envelope(status="unsupported-on-device",
                                   error="tool not present: ufw"),
            "nftables_ruleset": envelope(status="unsupported-on-device",
                                         error="tool not present: nft"),
            "iptables_rules": envelope(status="unsupported-on-device",
                                       error="tool not present: iptables"),
        },
        "backup_configuration": {
            "backup_tools": envelope(data={"tools": {
                "restic": None, "borg": None, "rsnapshot": None,
                "timeshift": None, "rclone": None, "duplicity": None}}),
            "backup_configs": envelope(data={"matches": []}),
        },
        "secret_file_locations": {
            "secret_files": envelope(data={"paths": [
                {"path": "/etc/ppp/pap-secrets", "type": "file",
                 "mode": "0o600", "uid": 0, "gid": 0, "size": 100,
                 "mtime": "2026-07-11T00:00:00+00:00"},
                {"path": "/etc/ssl/certs/ssl-cert-snakeoil.pem",
                 "type": "file", "mode": "0o644", "uid": 0, "gid": 0,
                 "size": 1000, "mtime": "2026-07-11T00:00:00+00:00"},
            ]}),
        },
        "cpu_memory_storage": {
            "filesystem_usage": envelope(data={"filesystems": [
                {"filesystem": "/dev/nvme0n1p2", "kb_total": "245578408",
                 "kb_used": "7035720", "kb_available": "228491008",
                 "use_percent": "3%", "mounted_on": "/"},
            ]}),
        },
        "hermes_installation": {
            "hermes_files": envelope(data={"matches": []}),
        },
    })


def pi_baseline_probes():
    return {
        "time_sync": envelope(data={"text_lines": [
            "NTP=yes", "NTPSynchronized=yes", "Timezone=Europe/Amsterdam"]}),
        "auto_upgrades_config": envelope(data={"present": False}),
        "var_log_perms": envelope(data={"matches": [
            {"path": "/var/log", "type": "dir", "mode": "0o755", "uid": 0,
             "gid": 0, "size": 4096, "mtime": "2026-07-11T00:00:00+00:00"},
            {"path": "/var/log/syslog", "type": "file", "mode": "0o640",
             "uid": 0, "gid": 4, "size": 1, "mtime": "2026-07-11T00:00:00+00:00"},
        ]}),
        "sshd_restart_policy": envelope(data={"text_lines": [
            "Restart=on-failure"]}),
    }


def hardened_inventory():
    report = pi_baseline_inventory()
    items = report["categories"]
    items["remote_access"]["items"]["sshd_config"] = envelope(data={
        "directives": {"passwordauthentication": ["no"],
                       "x11forwarding": ["no"],
                       "permitrootlogin": ["prohibit-password"]},
        "note": "selected directives only"})
    items["listening_ports"]["items"]["sockets"] = envelope(data={
        "text_lines": [PI_SOCKET_LINES[0], PI_SOCKET_LINES[4],
                       PI_SOCKET_LINES[5]]})
    items["firewall"]["items"]["nftables_ruleset"] = envelope(data={
        "text_lines": ["table inet filter {",
                       "chain input { type filter hook input priority 0; "
                       "policy drop;", "tcp dport 22 accept", "}"]})
    return report


def hardened_probes():
    probes = pi_baseline_probes()
    probes["auto_upgrades_config"] = envelope(data={"files": [
        {"path": "/etc/apt/apt.conf.d/20auto-upgrades",
         "content": 'APT::Periodic::Update-Package-Lists "1";\n'
                    'APT::Periodic::Unattended-Upgrade "1";\n'}]})
    return probes


def results_by_area(results):
    return {result.area: result for result in results}
