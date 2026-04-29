#!/usr/bin/env python3
# file: src/safe_ai_util_mcp/tools.py
# version: 1.1.0
# guid: 9b845c1f-81a6-4e86-a6b4-58d2ee51b9b3

"""Tool wrappers exposed via MCP.

Two execution paths:

* :func:`run_tool` — invoke ``safe-ai-util`` itself (file ops, git, buf,
  python, etc.). All path policy, audit logging, and per-command argument
  restrictions live in the Rust binary.
* :func:`run_direct` — invoke another binary (make, go, npm) that
  ``safe-ai-util`` does not have a dedicated subcommand for. The MCP
  schema is the trust boundary for these — agents only see narrowly-typed
  parameters (e.g. ``target: str``), not raw shell. We log every direct
  invocation so the burndown driver can audit them alongside safe-ai-util's
  own audit log.

Env-var passthrough: ``SAFE_AI_UTIL_REPO_ROOT``, ``SAFE_AI_UTIL_LOG_DIR``,
``SAFE_AI_UTIL_AUDIT_PATH``, ``SAFE_AI_UTIL_QUIET``, and ``SAFE_AI_UTIL_BIN``
are forwarded to subprocesses so callers (the burndown driver) can pin per-run
sandboxes without each tool re-discovering them.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional

DEFAULT_TIMEOUT = int(os.getenv("SAFE_AI_UTIL_TIMEOUT", "900"))  # seconds

# Env vars that the Rust util reads. Forwarded to every subprocess so callers
# can pin paths/quietness without each tool wrapping it.
_PASSTHROUGH_ENV_VARS = (
    "SAFE_AI_UTIL_BIN",
    "SAFE_AI_UTIL_REPO_ROOT",
    "SAFE_AI_UTIL_LOG_DIR",
    "SAFE_AI_UTIL_AUDIT_PATH",
    "SAFE_AI_UTIL_QUIET",
    "SAFE_AI_UTIL_MAX_READ_BYTES",
    "SAFE_AI_UTIL_MAX_WRITE_BYTES",
    "COPILOT_AGENT_ADDITIONAL_ARGS",
    "COPILOT_AUDIT_DIR",
)

_log = logging.getLogger("safe_ai_util_mcp")


def get_default_binary() -> str:
    """Resolve the safe-ai-util binary, supporting legacy name for compatibility."""
    env_bin = os.getenv("SAFE_AI_UTIL_BIN")
    if env_bin:
        return env_bin
    for candidate in ("safe-ai-util", "copilot-agent-util"):
        if shutil.which(candidate):
            return candidate
    return "safe-ai-util"


@dataclass
class RunResult:
    code: int
    stdout: str
    stderr: str


def _build_env(extra: Optional[dict] = None) -> dict:
    """Build a sanitized env that includes our passthrough vars."""
    base_env = {"PATH": os.getenv("PATH", "")}
    for key in ("HOME", "SHELL", "TERM", "LANG", "LC_ALL"):
        if key in os.environ:
            base_env[key] = os.environ[key]
    for key in _PASSTHROUGH_ENV_VARS:
        if key in os.environ:
            base_env[key] = os.environ[key]
    if extra:
        base_env.update(extra)
    return base_env


def run_tool(
    args: List[str],
    *,
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    stdin: Optional[str] = None,
) -> RunResult:
    """Run safe-ai-util with provided arguments, returning structured output."""
    bin_name = get_default_binary()
    base_env = _build_env(env)
    to = timeout or DEFAULT_TIMEOUT
    proc = subprocess.run(
        [bin_name, *args],
        cwd=cwd,
        env=base_env,
        capture_output=True,
        text=True,
        timeout=to,
        check=False,
        input=stdin,
    )
    return RunResult(proc.returncode, proc.stdout, proc.stderr)


def run_direct(
    binary: str,
    args: List[str],
    *,
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
) -> RunResult:
    """Run another binary directly (make/go/npm) under MCP-level audit.

    Use this only for tools that ``safe-ai-util`` lacks a built-in subcommand
    for. Each call is logged so the burndown driver can correlate against
    safe-ai-util's own audit.jsonl.
    """
    base_env = _build_env(env)
    to = timeout or DEFAULT_TIMEOUT
    _log.info("run_direct: %s %s (cwd=%s)", binary, args, cwd or "<inherit>")
    proc = subprocess.run(
        [binary, *args],
        cwd=cwd,
        env=base_env,
        capture_output=True,
        text=True,
        timeout=to,
        check=False,
    )
    return RunResult(proc.returncode, proc.stdout, proc.stderr)


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------

def tool_git_status() -> RunResult:
    return run_tool(["git", "status"])


def tool_git_add(pattern: str = ".") -> RunResult:
    return run_tool(["git", "add", pattern])


def tool_git_commit(message: str) -> RunResult:
    return run_tool(["git", "commit", "-m", message])


def tool_git_push(set_upstream: bool = False, branch: Optional[str] = None) -> RunResult:
    args = ["git", "push"]
    if set_upstream:
        args.append("--set-upstream")
    if branch:
        args += ["origin", branch]
    return run_tool(args)


def tool_git_branch(name: Optional[str] = None) -> RunResult:
    """List branches if name is None; create branch otherwise.

    Branch creation refuses ``main``/``master`` because the burndown driver
    expects per-task feature branches only.
    """
    if name is None:
        return run_tool(["git", "branch"])
    if name in {"main", "master"}:
        return RunResult(2, "", f"refusing to create reserved branch '{name}'")
    return run_tool(["git", "branch", name])


def tool_git_checkout(branch: str) -> RunResult:
    return run_tool(["git", "checkout", branch])


def tool_git_diff(target: Optional[str] = None) -> RunResult:
    args = ["git", "diff"]
    if target:
        args.append(target)
    return run_tool(args)


def tool_git_log(max_count: int = 20) -> RunResult:
    return run_tool(["git", "log", f"-{int(max_count)}", "--oneline"])


def tool_git_rebase(onto: str) -> RunResult:
    return run_tool(["git", "rebase", onto])


# ---------------------------------------------------------------------------
# fs (delegates to the new safe-ai-util `file` subcommand from PR #7)
# ---------------------------------------------------------------------------

def tool_fs_read(path: str, max_bytes: Optional[int] = None) -> RunResult:
    args = ["file", "read", "--path", path]
    if max_bytes is not None:
        args += ["--max-bytes", str(int(max_bytes))]
    return run_tool(args)


def tool_fs_read_lines(path: str, start: int = 1, end: Optional[int] = None) -> RunResult:
    """Read a 1-indexed line range from a file.

    Implemented in Python on top of fs_read so we don't need a new
    safe-ai-util subcommand. Returns just the requested slice as the
    stdout string. Lines are 1-indexed and inclusive on both ends.
    `end=None` means EOF.

    Use this for files that exceed the agent's context budget — read
    the chunk you need, not the whole file. The underlying fs_read
    still goes through the sandbox + audit log.
    """
    if start < 1:
        return RunResult(2, "", f"start must be >= 1, got {start}")
    if end is not None and end < start:
        return RunResult(2, "", f"end ({end}) must be >= start ({start})")
    raw = run_tool(["file", "read", "--path", path])
    if raw.code != 0:
        return raw
    lines = raw.stdout.splitlines(keepends=True)
    last = end if end is not None else len(lines)
    if start > len(lines):
        return RunResult(0, "", f"start={start} past EOF (file has {len(lines)} lines)")
    sliced = "".join(lines[start - 1 : last])
    return RunResult(0, sliced, "")


def tool_report_status(status: str, reason: str = "") -> RunResult:
    """Agent's structured "I am done" / "I am stuck" signal.

    The implementer agent calls this exactly once at the end of its loop
    so the harness can decide whether to open the PR as ready, draft, or
    skip it entirely. Stored in the MCP audit log so postmortem can see
    what the agent thought it was doing.

    Valid status values:
      complete   — work is done, tests pass (or none ran), PR can be
                   opened ready-for-review.
      partial    — partial fix landed but more is needed; PR should be
                   draft so a human finishes it.
      blocked    — could not proceed (missing context, destructive
                   error, hit a tool limit). PR should be draft (or
                   skipped if no diff was produced).

    The actual interpretation lives in the harness; this tool just
    captures + audits the signal. The "result" returned to the agent
    is a single line confirming what was recorded.
    """
    valid = {"complete", "partial", "blocked"}
    s = status.strip().lower()
    if s not in valid:
        return RunResult(2, "", f"status must be one of {sorted(valid)}, got {status!r}")
    payload = {"status": s, "reason": reason.strip()}
    _log.info("report_status: %s", payload)
    # Return the recorded payload as JSON so the agent can confirm; the
    # harness reads it from the MCP audit log via the same path.
    return RunResult(0, json.dumps(payload), "")


def tool_fs_write(
    path: str,
    content: str,
    create_dirs: bool = False,
    max_bytes: Optional[int] = None,
) -> RunResult:
    """Write content via stdin so we never put file payloads on the cmdline."""
    args = ["file", "write", "--path", path, "--content-stdin"]
    if create_dirs:
        args.append("--create-dirs")
    if max_bytes is not None:
        args += ["--max-bytes", str(int(max_bytes))]
    return run_tool(args, stdin=content)


def tool_fs_glob(pattern: str, max_results: Optional[int] = None) -> RunResult:
    args = ["file", "glob", "--pattern", pattern]
    if max_results is not None:
        args += ["--max-results", str(int(max_results))]
    return run_tool(args)


def tool_fs_list(path: str) -> RunResult:
    return run_tool(["file", "list", "--path", path])


def tool_fs_exists(path: str) -> RunResult:
    return run_tool(["file", "exists", "--path", path])


# ---------------------------------------------------------------------------
# buf
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# python (existing wrappers retained)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# direct-binary runners — make / go / npm
#
# These tools shell directly to the underlying binary because safe-ai-util
# does not (yet) provide a generic `system run` subcommand. The MCP schema is
# the trust boundary: agents only see narrow string parameters, never raw
# shell. Every call is logged via :func:`run_direct`.
# ---------------------------------------------------------------------------

def _repo_root_cwd(cwd: Optional[str]) -> Optional[str]:
    """Default cwd to SAFE_AI_UTIL_REPO_ROOT if the caller didn't set one.

    Without this, the agent's `go test ./...` runs from the MCP server's
    working dir (typically `/`) and fails with "directory prefix . does
    not contain main module or its selected dependencies." That bug
    accounted for ~30% of burndown-cell test-step failures on 2026-04-29.
    """
    if cwd:
        return cwd
    return os.environ.get("SAFE_AI_UTIL_REPO_ROOT") or None


def _go_env(extra: Optional[dict] = None) -> dict:
    """Default Go env: GOEXPERIMENT=jsonv2 (audiobook-organizer requires it).

    Caller-supplied env overrides ours. Agents shouldn't have to know
    about per-repo Go experiments — bake the common cases here so test
    runs don't spuriously fail with go.yaml.in indirect-dep errors.
    """
    env = {"GOEXPERIMENT": "jsonv2"}
    if extra:
        env.update(extra)
    return env


def tool_run_make(target: str, cwd: Optional[str] = None) -> RunResult:
    return run_direct("make", [target], cwd=_repo_root_cwd(cwd))


def tool_run_go_test(package: str = "./...", cwd: Optional[str] = None) -> RunResult:
    return run_direct("go", ["test", package], cwd=_repo_root_cwd(cwd), env=_go_env())


def tool_run_go_build(package: str = "./...", cwd: Optional[str] = None) -> RunResult:
    return run_direct("go", ["build", package], cwd=_repo_root_cwd(cwd), env=_go_env())


def tool_run_go_vet(package: str = "./...", cwd: Optional[str] = None) -> RunResult:
    return run_direct("go", ["vet", package], cwd=_repo_root_cwd(cwd), env=_go_env())


def tool_run_npm_test(cwd: Optional[str] = None) -> RunResult:
    return run_direct("npm", ["test"], cwd=_repo_root_cwd(cwd))


def tool_run_npm_ci(cwd: Optional[str] = None) -> RunResult:
    return run_direct("npm", ["ci"], cwd=_repo_root_cwd(cwd))
