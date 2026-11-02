#!/usr/bin/env python3
"""Tests for the locked-down one-shot call (change: rewrite-judge-lockdown).

No subprocess is started: every runner is a stub.
"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import atlas_oneshot as oneshot  # noqa: E402


def stream(text="ok", tools=(), servers=(), init=True, subtype="success",
           is_error=False, noise=True):
    lines = []
    if noise:
        lines.append("warning: not json")
    if init:
        lines.append(json.dumps({"type": "system", "subtype": "init",
                                 "cwd": "/tmp", "tools": list(tools),
                                 "mcp_servers": list(servers)}))
    lines.append(json.dumps({"type": "assistant", "message": {}}))
    lines.append(json.dumps({"type": "result", "subtype": subtype,
                             "is_error": is_error, "result": text}))
    return "\n".join(lines) + "\n"


class CallShapeTests(unittest.TestCase):
    def test_argv_has_no_tools_and_no_context(self):
        argv = oneshot.oneshot_argv("~/bin/claude", "sys")
        self.assertEqual(argv[0], os.path.expanduser("~/bin/claude"))
        self.assertEqual(argv[1], "-p")
        for flag in ("--restricted", "--strict-mcp-config",
                     "--disable-slash-commands", "--no-session-persistence",
                     "--verbose"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertEqual(argv[argv.index("--max-turns") + 1], "1")
        self.assertEqual(argv[argv.index("--output-format") + 1],
                         "stream-json")
        self.assertEqual(argv[-2:], ["--system-prompt", "sys"])
        # no MCP config, no model id, no Hermes
        self.assertNotIn("--mcp-config", argv)
        self.assertNotIn("--model", argv)
        self.assertFalse(any("hermes" in a for a in argv))

    def test_prompt_goes_on_stdin_outside_the_repo(self):
        seen = {}

        def runner(argv, **kwargs):
            seen.update(kwargs, argv=argv)
            return "done"
        self.assertEqual(oneshot.run_oneshot("PROMPT", "claude", "sys", 9.0,
                                             runner), "done")
        self.assertEqual(seen["input"], "PROMPT")
        self.assertNotIn("PROMPT", seen["argv"])
        self.assertEqual(seen["timeout"], 9.0)
        self.assertNotIn("atlas", seen["cwd"])

    def test_each_call_gets_a_private_empty_dir(self):
        seen = []

        def runner(argv, **kwargs):
            cwd = kwargs["cwd"]
            seen.append((cwd, os.listdir(cwd),
                         os.stat(cwd).st_mode & 0o777))
            return "done"
        for _ in range(2):
            oneshot.run_oneshot("P", "claude", "sys", 1.0, runner)
        (first, list1, mode1), (second, list2, _mode2) = seen
        self.assertNotEqual(first, second)
        self.assertEqual((list1, list2), ([], []))
        self.assertEqual(mode1, 0o700)
        self.assertEqual(os.path.dirname(first), oneshot.ONESHOT_CWD)
        self.assertFalse(os.path.exists(first))

    def test_dir_is_removed_when_the_call_raises(self):
        seen = []

        def runner(argv, **kwargs):
            seen.append(kwargs["cwd"])
            raise OSError("no binary")
        with self.assertRaises(OSError):
            oneshot.run_oneshot("P", "claude", "sys", 1.0, runner)
        self.assertFalse(os.path.exists(seen[0]))

    def test_nonce_is_random(self):
        self.assertNotEqual(oneshot.new_nonce(), oneshot.new_nonce())
        self.assertEqual(len(oneshot.new_nonce()), 16)


class SurfaceTests(unittest.TestCase):
    def test_empty_surface_returns_the_reply(self):
        self.assertEqual(oneshot.parse_stream(stream('{"a": 1}')), '{"a": 1}')

    def assertSurface(self, stdout):
        with self.assertRaises(oneshot.OneshotError) as caught:
            oneshot.parse_stream(stdout)
        self.assertTrue(caught.exception.surface)

    def test_any_tool_is_refused(self):
        self.assertSurface(stream(tools=["Read"]))

    def test_any_mcp_server_is_refused(self):
        self.assertSurface(stream(servers=[{"name": "atlas-kb"}]))

    def test_missing_init_is_refused(self):
        self.assertSurface(stream(init=False))
        self.assertSurface("")

    def test_a_later_init_with_tools_is_refused(self):
        clean = json.dumps({"type": "system", "subtype": "init",
                            "tools": [], "mcp_servers": []})
        dirty = json.dumps({"type": "system", "subtype": "init",
                            "tools": ["Bash"], "mcp_servers": []})
        self.assertSurface(clean + "\n" + dirty + "\n" + stream(init=False))

    def test_init_without_lists_is_refused(self):
        self.assertSurface(json.dumps({"type": "system",
                                       "subtype": "init"}) + "\n")

    def test_failed_result_is_not_a_surface_error(self):
        for stdout in (stream(subtype="error_max_turns"),
                       stream(is_error=True), stream(text=""),
                       stream(noise=False).split("\n")[0] + "\n"):
            with self.assertRaises(oneshot.OneshotError) as caught:
                oneshot.parse_stream(stdout)
            self.assertFalse(caught.exception.surface)


if __name__ == "__main__":
    unittest.main()
