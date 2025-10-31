#!/usr/bin/env python3
# file: src/safe_ai_util_mcp/server.py
# version: 1.0.0
# guid: c1d9d3c9-1268-4a48-8f91-3a6f9c6a2c38

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server

from . import get_default_binary
from . import tools as t


def build_server() -> Server:
    server = Server("safe-ai-util-mcp")

    # Helper to wrap results consistently
    def wrap(res: t.RunResult) -> Dict[str, Any]:
        return {"code": res.code, "stdout": res.stdout, "stderr": res.stderr}

    # Git tools
    @server.tool(
        "git_status",
        "Show git status",
        {
            "type": "object",
            "properties": {},
        },
    )
    async def git_status() -> Dict[str, Any]:
        return wrap(t.tool_git_status())

    @server.tool(
        "git_add",
        "git add <pattern> (default '.')",
        {
            "type": "object",
            "properties": {"pattern": {"type": "string", "default": "."}},
        },
    )
    async def git_add(pattern: str = ".") -> Dict[str, Any]:
        return wrap(t.tool_git_add(pattern))

    @server.tool(
        "git_commit",
        "git commit -m <message>",
        {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    )
    async def git_commit(message: str) -> Dict[str, Any]:
        return wrap(t.tool_git_commit(message))

    @server.tool(
        "git_push",
        "git push",
        {"type": "object", "properties": {}},
    )
    async def git_push() -> Dict[str, Any]:
        return wrap(t.tool_git_push())

    # Buf tools
    @server.tool(
        "buf_generate",
        "buf generate [--module <name>]",
        {
            "type": "object",
            "properties": {"module": {"type": "string"}},
        },
    )
    async def buf_generate(module: Optional[str] = None) -> Dict[str, Any]:
        return wrap(t.tool_buf_generate(module))

    @server.tool(
        "buf_lint",
        "buf lint [--module <name>]",
        {
            "type": "object",
            "properties": {"module": {"type": "string"}},
        },
    )
    async def buf_lint(module: Optional[str] = None) -> Dict[str, Any]:
        return wrap(t.tool_buf_lint(module))

    # Python workflows
    @server.tool(
        "py_venv_ensure",
        "Create or reuse a Python venv at path (default .venv)",
        {
            "type": "object",
            "properties": {"path": {"type": "string", "default": ".venv"}},
        },
    )
    async def py_venv_ensure(path: str = ".venv") -> Dict[str, Any]:
        return wrap(t.tool_py_venv_ensure(path))

    @server.tool(
        "py_pip_install",
        "Install dependencies via pip inside venv (optional requirements path)",
        {
            "type": "object",
            "properties": {"requirements": {"type": "string"}},
        },
    )
    async def py_pip_install(requirements: Optional[str] = None) -> Dict[str, Any]:
        return wrap(t.tool_py_pip_install(requirements))

    @server.tool(
        "py_pytest",
        "Run pytest via safe-ai-util (args optional)",
        {
            "type": "object",
            "properties": {"args": {"type": "string"}},
        },
    )
    async def py_pytest(args: Optional[str] = None) -> Dict[str, Any]:
        return wrap(t.tool_py_pytest(args))

    return server


async def _amain() -> None:
    # Resolve binary once to fail fast if not present
    _ = get_default_binary()

    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
