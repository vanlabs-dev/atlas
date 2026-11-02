#!/usr/bin/env python3
"""Locked-down one-shot model calls (change: rewrite-judge-lockdown).

The alert rewrite and the econ judge send untrusted text to a model. Each
call must reach a model that has no tools, no project context and no
memory, and must prove it per call. This module owns that call shape.

The calls do not go through Hermes. Every `hermes -z` call runs through the
Hermes gateway, which merges every enabled MCP server and other toolsets
into an explicit `-t` pick, so no Hermes flag gives an empty surface. The
calls run `claude -p` directly instead, with the login the runtime upgrade
job already uses:

- `--restricted`, `--tools ""`, `--strict-mcp-config` (and no
  `--mcp-config`): no built-in tools and no MCP servers.
- `--setting-sources ""`, `--disable-slash-commands`: no settings files,
  plugins, hooks or skills.
- `--max-turns 1`, `--no-session-persistence`: one turn, nothing kept.
- The prompt goes on stdin; the working directory is outside the
  repository, so no AGENTS.md or CLAUDE.md is found.

`stream-json` output carries an `init` event that lists the tools and MCP
servers of that very call. `parse_stream` refuses the reply unless the
event is present and both lists are empty. No model id is set: the CLI's
default model is used.

Standard library only. Callers inject the runner, so tests touch no
subprocess.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from typing import Any, Callable, List

ONESHOT_CWD = tempfile.gettempdir()

Runner = Callable[..., Any]

_FLAGS = ("-p", "--restricted", "--strict-mcp-config", "--tools", "",
          "--setting-sources", "", "--disable-slash-commands",
          "--max-turns", "1", "--no-session-persistence",
          "--output-format", "stream-json", "--verbose")


class OneshotError(Exception):
    """A call whose output cannot be used. `surface` is True when the
    call exposed a tool or MCP server, or did not report its surface."""

    def __init__(self, detail: str, surface: bool = False) -> None:
        super().__init__(detail)
        self.surface = surface


def new_nonce() -> str:
    return secrets.token_hex(8)


def oneshot_argv(claude_path: str, system_prompt: str) -> List[str]:
    return ([os.path.expanduser(claude_path)] + list(_FLAGS)
            + ["--system-prompt", system_prompt])


def run_oneshot(prompt: str, claude_path: str, system_prompt: str,
                timeout: float, runner: Runner) -> Any:
    """Run one call. Returns the completed process; raises what the runner
    raises (subprocess.TimeoutExpired, OSError)."""
    return runner(oneshot_argv(claude_path, system_prompt), input=prompt,
                  capture_output=True, text=True, timeout=timeout,
                  cwd=ONESHOT_CWD)


def parse_stream(stdout: str) -> str:
    """The reply text of one `stream-json` call. Raises OneshotError when
    the call reported a non-empty or missing tool surface, failed, or
    produced no result."""
    init = None
    result = None
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if (event.get("type") == "system" and event.get("subtype") == "init"
                and init is None):
            init = event
        elif event.get("type") == "result":
            result = event
    if init is None:
        raise OneshotError("no init event", surface=True)
    tools = init.get("tools")
    servers = init.get("mcp_servers")
    if not isinstance(tools, list) or not isinstance(servers, list):
        raise OneshotError("init event has no tool lists", surface=True)
    if tools or servers:
        raise OneshotError("call exposed %d tools and %d MCP servers"
                           % (len(tools), len(servers)), surface=True)
    if result is None:
        raise OneshotError("no result event")
    if result.get("is_error") or result.get("subtype") != "success":
        raise OneshotError("result %s" % (result.get("subtype") or "error"))
    text = result.get("result")
    if not isinstance(text, str) or not text.strip():
        raise OneshotError("empty result")
    return text
