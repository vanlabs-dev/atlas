"""Locked-down Hermes one-shot calls (change: rewrite-judge-lockdown)."""

import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))

import atlas_oneshot as oneshot  # noqa: E402

# The launcher chain as installed on the Pi (Hermes v0.22.5), trimmed.
WRAPPER = '#!/bin/sh\nexec /h/agent/.hermes/bin/hermes "$@"\n'
LAUNCHER = (
    "#!/bin/sh\n"
    "exec /h/tools/python-3.14.9/bin/python3 -I -c 'import os, re, sys\n"
    "sys.path.insert(0, '\"'\"'/h/agent'\"'\"')\n"
    "from hermes_cli.main import main\n"
    "sys.exit(main())\n"
    "' \"$@\"\n")
FILES = {"/bin/hermes": WRAPPER, "/h/agent/.hermes/bin/hermes": LAUNCHER}


class Done:
    def __init__(self, stdout="", returncode=0):
        self.stdout, self.returncode, self.stderr = stdout, returncode, ""


def probe_runner(result=None, returncode=0, raises=None):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if raises:
            raise raises
        out = "noise line\n" + (json.dumps(result) if result is not None
                                else "")
        return Done(out, returncode)
    run.calls = calls
    return run


class LauncherTests(unittest.TestCase):
    def test_follows_the_wrapper_to_the_real_interpreter(self):
        self.assertEqual(
            oneshot.launcher_runtime("/bin/hermes", FILES.__getitem__),
            ("/h/tools/python-3.14.9/bin/python3", "/h/agent"))

    def test_unknown_shape_is_an_error(self):
        with self.assertRaises(ValueError):
            oneshot.launcher_runtime("/x", lambda p: "#!/bin/sh\necho hi\n")


class VerifyTests(unittest.TestCase):
    def verify(self, runner, toolset="bot_room"):
        return oneshot.verify_no_tools("/bin/hermes", toolset, runner,
                                       FILES.__getitem__, cache={})

    def test_empty_valid_toolset_passes(self):
        runner = probe_runner({"valid": True, "tools": []})
        self.assertIsNone(self.verify(runner))
        argv, kwargs = runner.calls[0]
        self.assertEqual(argv[:3], ["/h/tools/python-3.14.9/bin/python3",
                                    "-I", "-c"])
        self.assertEqual(argv[-2:], ["/h/agent", "bot_room"])
        self.assertNotIn("atlas", kwargs["cwd"])

    def test_todo_is_refused(self):
        # B7: `todo` gives the model todo_list plus the tool_search bridge.
        runner = probe_runner({"valid": True, "tools": [
            "tool_search", "tool_describe", "tool_call"]})
        self.assertEqual(self.verify(runner, "todo"),
                         "toolset todo exposes 3 tools")

    def test_unknown_toolset_is_refused(self):
        runner = probe_runner({"valid": False, "tools": []})
        self.assertEqual(self.verify(runner, "none"),
                         "toolset none is unknown to Hermes")

    def test_probe_failures_fail_closed(self):
        for runner in (probe_runner(returncode=1),
                       probe_runner(None),
                       probe_runner({"tools": "x"}),
                       probe_runner(raises=OSError("gone")),
                       probe_runner(raises=subprocess.TimeoutExpired("p", 1))):
            self.assertIsNotNone(self.verify(runner))

    def test_empty_toolset_is_refused(self):
        self.assertEqual(self.verify(probe_runner(), ""),
                         "no toolset configured")

    def test_checked_once_per_process(self):
        cache = {}
        runner = probe_runner({"valid": True, "tools": []})
        for _ in range(3):
            oneshot.verify_no_tools("/bin/hermes", "bot_room", runner,
                                    FILES.__getitem__, cache=cache)
        self.assertEqual(len(runner.calls), 1)


class CallShapeTests(unittest.TestCase):
    def test_call_ignores_rules_and_leaves_the_repo(self):
        seen = {}

        def run(argv, **kwargs):
            seen.update(argv=argv, **kwargs)
            return Done("{}")
        oneshot.run_oneshot("p", "~/hermes", "bot_room", 5.0, run)
        self.assertEqual(seen["argv"][1:], ["-z", "p", "-t", "bot_room",
                                            "--ignore-rules"])
        self.assertEqual(seen["env"]["HERMES_IGNORE_RULES"], "1")
        self.assertEqual(seen["cwd"], oneshot.ONESHOT_CWD)
        self.assertEqual(oneshot.NO_TOOLS_TOOLSET, "bot_room")


if __name__ == "__main__":
    unittest.main()
