#!/usr/bin/env python3
# file: src/safe_ai_util_mcp/server.py
# version: 1.2.0
# guid: c1d9d3c9-1268-4a48-8f91-3a6f9c6a2c38

"""MCP stdio server exposing safe-ai-util operations as tools.

Uses the standard mcp.server pattern: a single ``@server.list_tools()`` handler
that returns the schema view, and a single ``@server.call_tool()`` handler that
dispatches to the wrapper functions in :mod:`safe_ai_util_mcp.tools` by name.

Tool surface:
  * git: status, add, commit, push, branch, checkout, diff, log, rebase
  * fs:  read, write, glob, list, exists (delegates to ``safe-ai-util file``)
  * buf: generate, lint
  * py:  venv ensure, pip install, pytest
  * run: make, go test/build/vet, npm test/ci
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import get_default_binary
from . import tools as t


# ---------------------------------------------------------------------------
# Tool registry — single source of truth for schemas + dispatch.
# ---------------------------------------------------------------------------

# Each entry: (name, description, input_schema, handler).
# The handler receives the raw arguments dict from the client and returns a
# RunResult. The list_tools/call_tool wrappers below convert to/from MCP types.

def _registry() -> List[tuple[str, str, Dict[str, Any], Callable[..., t.RunResult]]]:
    return [
        # --- git ---
        ("git_status", "Show git status",
         {"type": "object", "properties": {}},
         lambda a: t.tool_git_status()),
        ("git_add", "git add <pattern> (default '.')",
         {"type": "object", "properties": {"pattern": {"type": "string", "default": "."}}},
         lambda a: t.tool_git_add(a.get("pattern", "."))),
        ("git_commit", "git commit -m <message>",
         {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
         lambda a: t.tool_git_commit(a["message"])),
        ("git_push", "git push (optionally --set-upstream origin <branch>)",
         {"type": "object", "properties": {
             "set_upstream": {"type": "boolean", "default": False},
             "branch": {"type": "string"},
         }},
         lambda a: t.tool_git_push(set_upstream=a.get("set_upstream", False), branch=a.get("branch"))),
        ("git_branch",
         "List branches (no name) or create a new branch (name). main/master rejected.",
         {"type": "object", "properties": {"name": {"type": "string"}}},
         lambda a: t.tool_git_branch(a.get("name"))),
        ("git_checkout", "Switch to <branch>",
         {"type": "object", "properties": {"branch": {"type": "string"}}, "required": ["branch"]},
         lambda a: t.tool_git_checkout(a["branch"])),
        ("git_diff", "Show working-tree diff (optionally against <target>)",
         {"type": "object", "properties": {"target": {"type": "string"}}},
         lambda a: t.tool_git_diff(a.get("target"))),
        ("git_log", "Show recent commits, oneline, capped at <max_count>",
         {"type": "object", "properties": {"max_count": {"type": "integer", "default": 20}}},
         lambda a: t.tool_git_log(int(a.get("max_count", 20)))),
        ("git_rebase", "git rebase <onto>",
         {"type": "object", "properties": {"onto": {"type": "string"}}, "required": ["onto"]},
         lambda a: t.tool_git_rebase(a["onto"])),

        # --- fs (delegates to safe-ai-util file subcommand) ---
        ("fs_read",
         "Read a file (full contents). Supports files up to 10 MiB by default; "
         "override with the optional max_bytes argument. Path validated against "
         "repo-root sandbox if SAFE_AI_UTIL_REPO_ROOT is set. There is NO 4 KiB cap "
         "— do not assume one. For files you only need a slice of, prefer fs_read_lines.",
         {"type": "object", "properties": {
             "path": {"type": "string"},
             "max_bytes": {"type": "integer"},
         }, "required": ["path"]},
         lambda a: t.tool_fs_read(a["path"], a.get("max_bytes"))),
        ("fs_read_lines",
         "Read a 1-indexed inclusive line range from a file. Use this for large "
         "files when you only need a slice (e.g. just the function around line 240). "
         "Cheaper on context budget than fs_read of the whole file.",
         {"type": "object", "properties": {
             "path": {"type": "string"},
             "start": {"type": "integer", "minimum": 1, "default": 1},
             "end": {"type": "integer"},
         }, "required": ["path"]},
         lambda a: t.tool_fs_read_lines(a["path"], int(a.get("start", 1)), a.get("end"))),
        ("fs_write",
         "Write content to path (via stdin so payload is never on the cmdline).",
         {"type": "object", "properties": {
             "path": {"type": "string"},
             "content": {"type": "string"},
             "create_dirs": {"type": "boolean", "default": False},
             "max_bytes": {"type": "integer"},
         }, "required": ["path", "content"]},
         lambda a: t.tool_fs_write(a["path"], a["content"], a.get("create_dirs", False), a.get("max_bytes"))),
        ("fs_glob", "Match files against a glob pattern, one per line.",
         {"type": "object", "properties": {
             "pattern": {"type": "string"},
             "max_results": {"type": "integer"},
         }, "required": ["pattern"]},
         lambda a: t.tool_fs_glob(a["pattern"], a.get("max_results"))),
        ("fs_list", "List directory entries non-recursively, one per line.",
         {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
         lambda a: t.tool_fs_list(a["path"])),
        ("fs_exists", "Test whether path exists (code=0 yes, code=1 no).",
         {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
         lambda a: t.tool_fs_exists(a["path"])),

        # --- buf ---
        ("buf_generate", "buf generate [--module <name>]",
         {"type": "object", "properties": {"module": {"type": "string"}}},
         lambda a: t.tool_buf_generate(a.get("module"))),
        ("buf_lint", "buf lint [--module <name>]",
         {"type": "object", "properties": {"module": {"type": "string"}}},
         lambda a: t.tool_buf_lint(a.get("module"))),

        # --- python ---
        ("py_venv_ensure", "Create or reuse a Python venv at path (default .venv)",
         {"type": "object", "properties": {"path": {"type": "string", "default": ".venv"}}},
         lambda a: t.tool_py_venv_ensure(a.get("path", ".venv"))),
        ("py_pip_install", "Install dependencies via pip inside venv",
         {"type": "object", "properties": {"requirements": {"type": "string"}}},
         lambda a: t.tool_py_pip_install(a.get("requirements"))),
        ("py_pytest", "Run pytest via safe-ai-util",
         {"type": "object", "properties": {"args": {"type": "string"}}},
         lambda a: t.tool_py_pytest(a.get("args"))),

        # --- direct runners (no safe-ai-util built-in) ---
        ("run_make", "Run make <target>",
         {"type": "object", "properties": {
             "target": {"type": "string"},
             "cwd": {"type": "string"},
         }, "required": ["target"]},
         lambda a: t.tool_run_make(a["target"], a.get("cwd"))),
        ("run_go_test", "Run go test <package> (default ./...)",
         {"type": "object", "properties": {
             "package": {"type": "string", "default": "./..."},
             "cwd": {"type": "string"},
         }},
         lambda a: t.tool_run_go_test(a.get("package", "./..."), a.get("cwd"))),
        ("run_go_build", "Run go build <package> (default ./...)",
         {"type": "object", "properties": {
             "package": {"type": "string", "default": "./..."},
             "cwd": {"type": "string"},
         }},
         lambda a: t.tool_run_go_build(a.get("package", "./..."), a.get("cwd"))),
        ("run_go_vet", "Run go vet <package> (default ./...)",
         {"type": "object", "properties": {
             "package": {"type": "string", "default": "./..."},
             "cwd": {"type": "string"},
         }},
         lambda a: t.tool_run_go_vet(a.get("package", "./..."), a.get("cwd"))),
        ("run_npm_test", "Run npm test",
         {"type": "object", "properties": {"cwd": {"type": "string"}}},
         lambda a: t.tool_run_npm_test(a.get("cwd"))),
        ("run_npm_ci", "Run npm ci",
         {"type": "object", "properties": {"cwd": {"type": "string"}}},
         lambda a: t.tool_run_npm_ci(a.get("cwd"))),

        # --- Agent self-report ---
        ("report_status",
         "Signal whether the task is complete, partial, or blocked. The "
         "harness uses this to decide whether to open the PR as ready or "
         "draft, what labels to apply, and whether to skip PR creation "
         "entirely. Call this exactly once at the end of your loop, "
         "BEFORE you stop calling tools. status must be one of: "
         "'complete' (work is done, ready for review), 'partial' (some "
         "progress, more needed), 'blocked' (could not proceed; explain "
         "in reason).",
         {"type": "object", "properties": {
             "status": {"type": "string", "enum": ["complete", "partial", "blocked"]},
             "reason": {"type": "string"},
         }, "required": ["status"]},
         lambda a: t.tool_report_status(a["status"], a.get("reason", ""))),
    ]


# ---------------------------------------------------------------------------
# Server construction
# ---------------------------------------------------------------------------

def registered_tool_names() -> List[str]:
    """Public helper used by tests to assert the registry has the right shape."""
    return [name for name, _, _, _ in _registry()]


def build_server() -> Server:
    server = Server("safe-ai-util-mcp")
    reg = _registry()
    by_name: Dict[str, Callable[..., t.RunResult]] = {name: h for name, _, _, h in reg}
    schemas = [Tool(name=name, description=desc, inputSchema=schema)
               for name, desc, schema, _ in reg]

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return schemas

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
        handler = by_name.get(name)
        if handler is None:
            raise ValueError(f"unknown tool: {name}")
        result = handler(arguments or {})
        # Encode RunResult as JSON text content. Drivers parse {code, stdout, stderr}.
        payload = json.dumps({
            "code": result.code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        })
        return [TextContent(type="text", text=payload)]

    return server


async def _amain() -> None:
    _ = get_default_binary()
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
