#!/usr/bin/env python3
# file: src/safe_ai_util_mcp/tools.py
# version: 1.0.0
# guid: 9b845c1f-81a6-4e86-a6b4-58d2ee51b9b3

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional

DEFAULT_TIMEOUT = int(os.getenv("SAFE_AI_UTIL_TIMEOUT", "900"))  # seconds


def get_default_binary() -> str:
    """Resolve the safe-ai-util binary, supporting legacy name for compatibility."""
    env_bin = os.getenv("SAFE_AI_UTIL_BIN")
    if env_bin:
        return env_bin
    for candidate in ("safe-ai-util", "copilot-agent-util"):
        if shutil.which(candidate):
            return candidate
    # Fallback to name; subprocess will error if missing
    return "safe-ai-util"


@dataclass
class RunResult:
    code: int
    stdout: str
    stderr: str


def run_tool(
    args: List[str],
    *,
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
) -> RunResult:
    """Run the safe-ai-util tool with provided arguments, returning structured output.

    This uses the hardened Rust utility for actual execution.
    """
    bin_name = get_default_binary()

    # Minimal, sanitized env – inherit PATH and selected variables
    base_env = {"PATH": os.getenv("PATH", "")}
    for key in ("HOME", "SHELL", "TERM", "LANG", "LC_ALL"):
        if key in os.environ:
            base_env[key] = os.environ[key]
    if env:
        base_env.update(env)

    to = timeout or DEFAULT_TIMEOUT

    proc = subprocess.run(
        [bin_name, *args],
        cwd=cwd,
        env=base_env,
        capture_output=True,
        text=True,
        timeout=to,
        check=False,
    )
    return RunResult(proc.returncode, proc.stdout, proc.stderr)


# Convenience wrappers mapping to common workflows


def tool_git_add(pattern: str = ".") -> RunResult:
    return run_tool(["git", "add", pattern])


def tool_git_commit(message: str) -> RunResult:
    return run_tool(["git", "commit", "-m", message])


def tool_git_push() -> RunResult:
    return run_tool(["git", "push"])  # auth handled by environment


def tool_git_status() -> RunResult:
    return run_tool(["git", "status"])


def tool_buf_generate(module: Optional[str] = None) -> RunResult:
    args = ["buf", "generate"]
    if module:
        args += ["--module", module]
    return run_tool(args)


def tool_buf_lint(module: Optional[str] = None) -> RunResult:
    args = ["buf", "lint"]
    if module:
        args += ["--module", module]
    return run_tool(args)


def tool_py_venv_ensure(path: str = ".venv") -> RunResult:
    return run_tool(["python", "venv", "ensure", "--path", path])


def tool_py_venv_remove(path: str = ".venv") -> RunResult:
    return run_tool(["python", "venv", "remove", "--path", path])


def tool_py_pip_install(requirements: Optional[str] = None) -> RunResult:
    args = ["python", "pip", "install"]
    if requirements:
        args += ["--requirements", requirements]
    return run_tool(args)


def tool_py_pytest(pytest_args: Optional[str] = None) -> RunResult:
    args = ["python", "run", "pytest"]
    if pytest_args:
        args += pytest_args.split()
    return run_tool(args)
