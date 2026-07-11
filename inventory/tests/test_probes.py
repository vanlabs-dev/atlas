"""Per-probe parser and status-mapping tests (spec: Explicit per-item status)."""

import os
import tempfile
import unittest
from unittest import mock

from _helpers import ai, FakeExec, timeout_exc


PASSWD = (
    "root:x:0:0:root:/root:/bin/bash\n"
    "daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
    "pi:x:1000:1000:,,,:/home/pi:/bin/bash\n"
)

OS_RELEASE = (
    'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\n'
    'ID=debian\nVERSION_ID="12"\n'
)

DPKG = "git\t1:2.39.2\nlibfoo\t1.0\npython3\t3.11.2\nbittensor-cli\t9.0.0\n"

SSHD = (
    "# comment\n"
    "Port 22\n"
    "PasswordAuthentication no\n"
    "PermitRootLogin prohibit-password\n"
    "Subsystem sftp /usr/lib/openssh/sftp-server\n"
)

DF = (
    "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
    "/dev/nvme0n1p2 245000000 30000000 202000000 13% /\n"
    "/dev/nvme0n1p1 522230 62000 460230 12% /boot\n"
)

MEMINFO = (
    "MemTotal:       16265216 kB\nMemFree:        14265216 kB\n"
    "MemAvailable:   15265216 kB\nBuffers:          123456 kB\n"
    "SwapTotal:        102396 kB\nSwapFree:         102396 kB\n"
)


def probe_by_id(item_id):
    matches = [p for p in ai.PROBES if p.item_id == item_id]
    assert len(matches) == 1, item_id
    return matches[0]


class ParserTests(unittest.TestCase):
    def test_passwd(self):
        data = ai.PARSERS["passwd"]([("/etc/passwd", PASSWD)])
        self.assertEqual(len(data["users"]), 3)
        self.assertEqual(data["users"][2]["name"], "pi")
        self.assertEqual(data["users"][2]["shell"], "/bin/bash")
        self.assertIn("shadow", data["note"])

    def test_os_release(self):
        data = ai.PARSERS["os_release"]([("/etc/os-release", OS_RELEASE)])
        self.assertEqual(data["os_release"]["ID"], "debian")
        self.assertEqual(data["os_release"]["PRETTY_NAME"],
                         "Debian GNU/Linux 12 (bookworm)")

    def test_dpkg_relevance_filter(self):
        data = ai.PARSERS["dpkg_relevant"](DPKG)
        self.assertEqual(data["total_installed"], 4)
        names = [p["name"] for p in data["relevant"]]
        self.assertEqual(names, ["git", "python3", "bittensor-cli"])

    def test_sshd_selected_directives_only(self):
        data = ai.PARSERS["sshd_config"]([("/etc/ssh/sshd_config", SSHD)])
        self.assertEqual(data["directives"]["port"], ["22"])
        self.assertEqual(data["directives"]["passwordauthentication"], ["no"])
        self.assertNotIn("subsystem", data["directives"])

    def test_df(self):
        data = ai.PARSERS["df"](DF)
        self.assertEqual(len(data["filesystems"]), 2)
        self.assertEqual(data["filesystems"][0]["mounted_on"], "/")

    def test_meminfo_subset(self):
        data = ai.PARSERS["meminfo"]([("/proc/meminfo", MEMINFO)])
        self.assertEqual(set(data["meminfo"]),
                         {"MemTotal", "MemFree", "MemAvailable",
                          "SwapTotal", "SwapFree"})

    def test_json_lines_tolerates_bad_lines(self):
        data = ai.PARSERS["json_lines"]('{"Names": "web"}\nnot json\n')
        self.assertEqual(data["entries"], [{"Names": "web"}])
        self.assertEqual(data["unparsed_lines"], 1)

    def test_find_paths_stats_real_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "repo.git")
            os.mkdir(target)
            data = ai.PARSERS["find_paths"](target + "\n" + os.path.join(tmp, "gone") + "\n")
            self.assertEqual(data["paths"][0]["type"], "dir")
            self.assertEqual(data["paths"][1]["error"], "not found")


class StatusMappingTests(unittest.TestCase):
    def run_probe(self, item_id, executor):
        return ai.run_probe(probe_by_id(item_id), executor)

    def test_missing_tool_is_unsupported(self):
        env = self.run_probe("cpu", FakeExec(raises=FileNotFoundError("lscpu")))
        self.assertEqual(env["status"], "unsupported-on-device")
        self.assertIn("lscpu", env["error"])

    def test_permission_error_is_denied(self):
        env = self.run_probe("cpu", FakeExec(raises=PermissionError("denied")))
        self.assertEqual(env["status"], "permission-denied")

    def test_timeout_is_error(self):
        env = self.run_probe("cpu", FakeExec(raises=timeout_exc()))
        self.assertEqual(env["status"], "error")
        self.assertIn("timed out", env["error"])

    def test_root_required_stderr_is_denied(self):
        env = self.run_probe("ufw_status", FakeExec(
            returncode=1, stderr=b"ERROR: You need to be root to run this script"))
        self.assertEqual(env["status"], "permission-denied")

    def test_nonzero_exit_is_error(self):
        env = self.run_probe("cpu", FakeExec(returncode=2, stderr=b"boom"))
        self.assertEqual(env["status"], "error")
        self.assertIn("exit 2", env["error"])

    def test_empty_crontab_is_a_finding_not_an_error(self):
        env = self.run_probe("user_crontab", FakeExec(
            returncode=1, stderr=b"no crontab for pi"))
        self.assertEqual(env["status"], "collected")
        self.assertEqual(env["data"], {"text_lines": []})

    def test_partial_find_results_collected_with_warning(self):
        env = self.run_probe("git_repositories", FakeExec(
            returncode=1, stdout=b"/home/pi/subtensor/.git\n",
            stderr=b"find: '/root': Permission denied"))
        self.assertEqual(env["status"], "collected")
        self.assertTrue(any("partial" in w for w in env["warnings"]))

    def test_parser_failure_is_error_not_crash(self):
        env = self.run_probe("block_devices", FakeExec(stdout=b"not json at all"))
        self.assertEqual(env["status"], "error")
        self.assertIn("parser failed", env["error"])

    def test_probe_output_is_redacted(self):
        env = self.run_probe("sockets", FakeExec(
            stdout=b'users:(("proc --token PLANTEDSOCKET"))'))
        self.assertNotIn("PLANTEDSOCKET", str(env))

    def test_command_recorded_in_envelope(self):
        env = self.run_probe("architecture", FakeExec(stdout=b"aarch64\n"))
        self.assertEqual(env["command"], "uname -m")
        self.assertEqual(env["data"]["text_lines"], ["aarch64"])


class ReadProbeTests(unittest.TestCase):
    def test_missing_ok_reports_absence_as_finding(self):
        env = ai.run_probe(probe_by_id("hermes_version_files"))
        # none of the hermes version paths exist on the dev machine
        self.assertEqual(env["status"], "collected")
        self.assertEqual(env["data"], {"present": False})

    def test_missing_required_file_is_unsupported(self):
        probe = ai.Probe("x", "os_kernel", "read", ("/definitely/not/here",))
        env = ai.run_probe(probe)
        self.assertEqual(env["status"], "unsupported-on-device")

    def test_reads_and_redacts_real_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("host=db.local\napi_key=PLANTEDREAD01\n")
            probe = ai.Probe("x", "os_kernel", "read", (path,))
            env = ai.run_probe(probe)
        self.assertEqual(env["status"], "collected")
        self.assertNotIn("PLANTEDREAD01", str(env))
        self.assertIn("host=db.local", env["data"]["files"][0]["content"])

    def test_permission_denied_on_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "locked")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("x")
            probe = ai.Probe("x", "os_kernel", "read", (path,))
            with mock.patch("builtins.open", side_effect=PermissionError("locked")):
                env = ai.run_probe(probe)
        self.assertEqual(env["status"], "permission-denied")


class StatGlobAndWhichTests(unittest.TestCase):
    def test_stat_glob_lists_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = os.path.join(tmp, ".env")
            with open(secret, "w", encoding="utf-8") as handle:
                handle.write("API_KEY=PLANTEDSTAT01")
            probe = ai.Probe("x", "secret_file_locations", "stat-glob",
                             (os.path.join(tmp, ".env*"),))
            env = ai.run_probe(probe)
        self.assertEqual(env["status"], "collected")
        match = env["data"]["matches"][0]
        self.assertEqual(match["type"], "file")
        self.assertIn("mode", match)
        # contents must never be read
        self.assertNotIn("PLANTEDSTAT01", str(env))

    def test_stat_glob_no_matches_is_a_finding(self):
        probe = ai.Probe("x", "hermes_installation", "stat-glob",
                         ("/definitely/not/here/*",))
        env = ai.run_probe(probe)
        self.assertEqual(env["status"], "collected")
        self.assertEqual(env["data"]["matches"], [])

    def test_which_probe(self):
        probe = ai.Probe("x", "backup_configuration", "which",
                         ("python", "definitely-not-a-tool-xyz"))
        env = ai.run_probe(probe)
        self.assertEqual(env["status"], "collected")
        self.assertIsNone(env["data"]["tools"]["definitely-not-a-tool-xyz"])


class ProbeTableTests(unittest.TestCase):
    def test_every_probe_category_is_declared(self):
        for probe in ai.PROBES:
            self.assertIn(probe.category, ai.CATEGORIES, probe.item_id)

    def test_every_category_has_at_least_one_probe(self):
        covered = {probe.category for probe in ai.PROBES}
        self.assertEqual(covered, set(ai.CATEGORIES))

    def test_declared_parsers_exist(self):
        for probe in ai.PROBES:
            if probe.parser:
                self.assertIn(probe.parser, ai.PARSERS, probe.item_id)

    def test_no_shell_metacharacters_in_cmd_probes(self):
        # argv execution only; a metacharacter would hint at shell reliance
        for probe in ai.PROBES:
            if probe.kind == "cmd":
                for arg in probe.spec:
                    self.assertNotIn(";", arg, probe.item_id)
                    self.assertNotIn("&&", arg, probe.item_id)
                    self.assertNotIn(">", arg, probe.item_id)


if __name__ == "__main__":
    unittest.main()
