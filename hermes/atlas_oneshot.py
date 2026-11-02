#!/usr/bin/env python3
"""Locked-down Hermes one-shot calls (change: rewrite-judge-lockdown).

The alert rewrite and the econ judge send untrusted text to the local
Hermes one-shot CLI. One-shot mode bypasses approvals, so each call must
reach a model that has no tools, no project context and no memory. This
module owns that call shape and the startup check that proves it.

- `NO_TOOLS_TOOLSET` is a Hermes toolset that resolves to zero tools.
  Hermes has no named empty toolset; `bot_room` is a feature toolset that is
  empty today. `verify_no_tools` asks the installed Hermes, through the
  launcher's own interpreter, what the toolset resolves to, and fails
  closed on any tool, any error or any parse failure.
- `oneshot_argv` adds `--ignore-rules`, and `oneshot_env` sets
  `HERMES_IGNORE_RULES`, so no AGENTS.md, SOUL.md, memory or skill text
  enters the prompt. `ONESHOT_CWD` keeps the call out of the repository.
- `new_nonce` gives each prompt a fence tag the data cannot predict.

Standard library only. Callers inject the runner, so tests touch no
subprocess.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

NO_TOOLS_TOOLSET = "bot_room"
ONESHOT_CWD = tempfile.gettempdir()
PROBE_TIMEOUT_SECONDS = 60.0

Runner = Callable[..., Any]

# The launcher chain on the Pi: `~/.local/bin/hermes` is `exec <launcher>`,
# and the launcher is `exec <python> -I -c '...sys.path.insert(0, <root>)'`.
_EXEC_RE = re.compile(r"^\s*exec\s+(\S+)(.*)$", re.MULTILINE)
_ROOT_RE = re.compile(r"sys\.path\.insert\(0,\s*'\"'\"'([^'\"]+)'\"'\"'\)"
                      r"|sys\.path\.insert\(0,\s*['\"]([^'\"]+)['\"]\)")

# Runs inside the Hermes runtime. Prints one JSON line: whether the
# toolset name is valid for `-t`, and the tool definitions it yields.
_PROBE = (
    "import sys, json, logging\n"
    "root, name = sys.argv[1], sys.argv[2]\n"
    "sys.path.insert(0, root)\n"
    "sys._hermes_pin_default_home = True\n"
    "import hermes_bootstrap\n"
    "logging.disable(logging.CRITICAL)\n"
    "import toolsets, model_tools\n"
    "defs = model_tools.get_tool_definitions(enabled_toolsets=[name], "
    "quiet_mode=True)\n"
    "print(json.dumps({'valid': bool(toolsets.validate_toolset(name)), "
    "'tools': [d['function']['name'] for d in defs]}))\n"
)

_verified: Dict[Tuple[str, str], Optional[str]] = {}


def new_nonce() -> str:
    return secrets.token_hex(8)


def oneshot_argv(hermes_path: str, prompt: str, toolset: str) -> List[str]:
    return [os.path.expanduser(hermes_path), "-z", prompt, "-t", toolset,
            "--ignore-rules"]


def oneshot_env() -> Dict[str, str]:
    env = dict(os.environ)
    env["HERMES_IGNORE_RULES"] = "1"
    return env


def run_oneshot(prompt: str, hermes_path: str, toolset: str,
                timeout: float, runner: Runner) -> Any:
    return runner(oneshot_argv(hermes_path, prompt, toolset),
                  capture_output=True, text=True, timeout=timeout,
                  cwd=ONESHOT_CWD, env=oneshot_env())


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read(65536)


def launcher_runtime(hermes_path: str,
                     reader: Callable[[str], str] = _read
                     ) -> Tuple[str, str]:
    """(interpreter, Hermes root) that `hermes_path` really runs. Follows
    shell `exec` wrappers until it reaches the Python launcher. Raises
    ValueError when the chain has an unexpected shape."""
    path = os.path.expanduser(hermes_path)
    for _hop in range(4):
        text = reader(path)
        match = _EXEC_RE.search(text)
        if not match:
            raise ValueError("no exec line in %s" % path)
        target, rest = match.group(1), match.group(2)
        if " -c " in rest or rest.strip().startswith("-I"):
            root = _ROOT_RE.search(text)
            if not root:
                raise ValueError("no Hermes root in %s" % path)
            return target, root.group(1) or root.group(2)
        path = target
    raise ValueError("launcher chain too deep at %s" % path)


def probe_toolset(hermes_path: str, toolset: str, runner: Runner,
                  reader: Callable[[str], str] = _read
                  ) -> Dict[str, Any]:
    """Ask the installed Hermes what `toolset` resolves to. Raises
    ValueError on any failure."""
    python, root = launcher_runtime(hermes_path, reader)
    try:
        done = runner([python, "-I", "-c", _PROBE, root, toolset],
                      capture_output=True, text=True,
                      timeout=PROBE_TIMEOUT_SECONDS, cwd=ONESHOT_CWD)
    except subprocess.TimeoutExpired:
        raise ValueError("probe timed out")
    except OSError as exc:
        raise ValueError("probe failed to start: %s" % exc)
    if done.returncode != 0:
        raise ValueError("probe exit %s" % done.returncode)
    lines = [l for l in (done.stdout or "").splitlines() if l.strip()]
    try:
        result = json.loads(lines[-1])
    except (IndexError, ValueError):
        raise ValueError("probe output unreadable")
    if (not isinstance(result, dict)
            or not isinstance(result.get("tools"), list)):
        raise ValueError("probe output has the wrong shape")
    return result


def verify_no_tools(hermes_path: str, toolset: str, runner: Runner,
                    reader: Callable[[str], str] = _read,
                    cache: Optional[Dict[Tuple[str, str], Optional[str]]]
                    = None) -> Optional[str]:
    """None when `toolset` is valid and yields no tools in the installed
    Hermes; else a short reason. Checked once per process."""
    memo = _verified if cache is None else cache
    key = (hermes_path, toolset)
    if key in memo:
        return memo[key]
    if not toolset:
        problem: Optional[str] = "no toolset configured"
    else:
        try:
            result = probe_toolset(hermes_path, toolset, runner, reader)
        except ValueError as exc:
            problem = str(exc)
        else:
            if not result.get("valid"):
                problem = "toolset %s is unknown to Hermes" % toolset
            elif result["tools"]:
                problem = "toolset %s exposes %d tools" % (
                    toolset, len(result["tools"]))
            else:
                problem = None
    memo[key] = problem
    return problem
