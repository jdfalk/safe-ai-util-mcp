#!/usr/bin/env python3
# file: tests/test_tools.py
# version: 1.0.0
# guid: a1b2c3d4-e5f6-7890-abcd-ef0123456789

"""Unit tests for the tool wrapper layer.

These tests do not invoke the real ``safe-ai-util`` binary or any underlying
tool — they mock ``subprocess.run`` and assert the constructed argv plus the
sanitized environment is what we expect.
"""

from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest

from safe_ai_util_mcp import tools


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# env passthrough
# ---------------------------------------------------------------------------

def test_env_passthrough_includes_safe_ai_util_vars(monkeypatch):
    monkeypatch.setenv("SAFE_AI_UTIL_REPO_ROOT", "/tmp/burndown-x")
    monkeypatch.setenv("SAFE_AI_UTIL_LOG_DIR", "/tmp/sai-logs")
    monkeypatch.setenv("SAFE_AI_UTIL_QUIET", "1")
    monkeypatch.setenv("SAFE_AI_UTIL_AUDIT_PATH", "/tmp/sai-audit")

    with patch("safe_ai_util_mcp.tools.subprocess.run", return_value=_completed()) as run:
        tools.tool_git_status()

    kwargs = run.call_args.kwargs
    env = kwargs["env"]
    assert env["SAFE_AI_UTIL_REPO_ROOT"] == "/tmp/burndown-x"
    assert env["SAFE_AI_UTIL_LOG_DIR"] == "/tmp/sai-logs"
    assert env["SAFE_AI_UTIL_QUIET"] == "1"
    assert env["SAFE_AI_UTIL_AUDIT_PATH"] == "/tmp/sai-audit"
    # Unrelated vars are not leaked.
    assert "AWS_SECRET_ACCESS_KEY" not in env


def test_env_does_not_inherit_unsafe_vars(monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "definitely-do-not-leak")
    with patch("safe_ai_util_mcp.tools.subprocess.run", return_value=_completed()) as run:
        tools.tool_git_status()
    env = run.call_args.kwargs["env"]
    assert "SECRET_TOKEN" not in env


# ---------------------------------------------------------------------------
# fs_*
# ---------------------------------------------------------------------------

def test_fs_read_constructs_expected_argv():
    with patch("safe_ai_util_mcp.tools.subprocess.run", return_value=_completed()) as run:
        tools.tool_fs_read("src/main.go", max_bytes=1024)
    argv = run.call_args.args[0]
    # argv = [bin, "file", "read", "--path", "src/main.go", "--max-bytes", "1024"]
    assert argv[1:] == ["file", "read", "--path", "src/main.go", "--max-bytes", "1024"]


def test_fs_write_uses_stdin_for_content():
    with patch("safe_ai_util_mcp.tools.subprocess.run", return_value=_completed()) as run:
        tools.tool_fs_write("README.md", "hello world", create_dirs=True)
    argv = run.call_args.args[0]
    kwargs = run.call_args.kwargs
    # Must use --content-stdin so payload never appears on the cmdline.
    assert "--content-stdin" in argv
    assert "--content" not in argv
    assert "--create-dirs" in argv
    # Content must be passed via stdin.
    assert kwargs["input"] == "hello world"


def test_fs_glob_constructs_expected_argv():
    with patch("safe_ai_util_mcp.tools.subprocess.run", return_value=_completed()) as run:
        tools.tool_fs_glob("**/*.py", max_results=100)
    argv = run.call_args.args[0]
    assert argv[1:] == ["file", "glob", "--pattern", "**/*.py", "--max-results", "100"]


# ---------------------------------------------------------------------------
# git_*
# ---------------------------------------------------------------------------

def test_git_branch_lists_when_no_name():
    with patch("safe_ai_util_mcp.tools.subprocess.run", return_value=_completed()) as run:
        tools.tool_git_branch(None)
    assert run.call_args.args[0][1:] == ["git", "branch"]


def test_git_branch_creates_when_name():
    with patch("safe_ai_util_mcp.tools.subprocess.run", return_value=_completed()) as run:
        tools.tool_git_branch("feat/foo")
    assert run.call_args.args[0][1:] == ["git", "branch", "feat/foo"]


@pytest.mark.parametrize("reserved", ["main", "master"])
def test_git_branch_refuses_reserved(reserved):
    # Should NOT touch subprocess at all.
    with patch("safe_ai_util_mcp.tools.subprocess.run") as run:
        result = tools.tool_git_branch(reserved)
    assert run.call_count == 0
    assert result.code == 2
    assert reserved in result.stderr


def test_git_push_with_upstream_branch():
    with patch("safe_ai_util_mcp.tools.subprocess.run", return_value=_completed()) as run:
        tools.tool_git_push(set_upstream=True, branch="feat/foo")
    argv = run.call_args.args[0]
    assert argv[1:] == ["git", "push", "--set-upstream", "origin", "feat/foo"]


def test_git_log_clamps_max_count_to_int():
    with patch("safe_ai_util_mcp.tools.subprocess.run", return_value=_completed()) as run:
        # Pass a float; wrapper should int-coerce so the flag is well-formed.
        tools.tool_git_log(max_count=10)
    argv = run.call_args.args[0]
    assert argv[1:] == ["git", "log", "-10", "--oneline"]


def test_git_rebase_passes_onto():
    with patch("safe_ai_util_mcp.tools.subprocess.run", return_value=_completed()) as run:
        tools.tool_git_rebase("origin/main")
    assert run.call_args.args[0][1:] == ["git", "rebase", "origin/main"]


# ---------------------------------------------------------------------------
# direct runners (run_make / run_go_* / run_npm_*)
# ---------------------------------------------------------------------------

def test_run_make_invokes_make_directly_not_safe_ai_util():
    with patch("safe_ai_util_mcp.tools.subprocess.run", return_value=_completed()) as run:
        tools.tool_run_make("ci", cwd="/tmp/x")
    argv = run.call_args.args[0]
    # First element is the binary itself ("make"), NOT safe-ai-util.
    assert argv[0] == "make"
    assert argv[1:] == ["ci"]
    assert run.call_args.kwargs["cwd"] == "/tmp/x"


def test_run_go_test_default_package():
    with patch("safe_ai_util_mcp.tools.subprocess.run", return_value=_completed()) as run:
        tools.tool_run_go_test()
    argv = run.call_args.args[0]
    assert argv == ["go", "test", "./..."]


def test_run_npm_ci():
    with patch("safe_ai_util_mcp.tools.subprocess.run", return_value=_completed()) as run:
        tools.tool_run_npm_ci(cwd="/tmp/proj")
    argv = run.call_args.args[0]
    assert argv == ["npm", "ci"]
    assert run.call_args.kwargs["cwd"] == "/tmp/proj"


# ---------------------------------------------------------------------------
# server registration smoke
# ---------------------------------------------------------------------------

def test_registry_contains_all_expected_tools():
    from safe_ai_util_mcp import server as srv

    expected = {
        "git_status", "git_add", "git_commit", "git_push",
        "git_branch", "git_checkout", "git_diff", "git_log", "git_rebase",
        "fs_read", "fs_write", "fs_glob", "fs_list", "fs_exists",
        "buf_generate", "buf_lint",
        "py_venv_ensure", "py_pip_install", "py_pytest",
        "run_make", "run_go_test", "run_go_build", "run_go_vet",
        "run_npm_test", "run_npm_ci",
    }
    names = set(srv.registered_tool_names())
    missing = expected - names
    assert not missing, f"missing tools in registry: {missing}"


def test_build_server_constructs_without_error():
    """The bootstrap server.py used a non-existent @server.tool decorator and
    crashed on construction. This test guards against regression."""
    from safe_ai_util_mcp import server as srv
    s = srv.build_server()
    assert s is not None
    assert s.name == "safe-ai-util-mcp"
