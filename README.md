<!-- file: README.md -->
<!-- version: 0.1.0 -->
<!-- guid: 7b8e3f2d-1c45-4a7a-9b6c-2f3d4e5a6b7c -->

# safe-ai-util-mcp

Model Context Protocol (MCP) server that exposes the capabilities of the `safe-ai-util` tool to AI clients (Claude Desktop, Continue.dev, GitHub Copilot when available) over stdio.

## Status

- Bootstrap commit. Server implementation to follow.

## Goals

- Safe, audited execution of common developer operations via `safe-ai-util`:
  - Git (status/add/commit/push)
  - Buf (lint/generate)
  - Python workflows (venv/pip/pytest)
- Clear JSON schemas for tools
- Strong guardrails (timeouts, sanitized env, path validation)

## Quick start (planned)

```bash
python -m venv .venv
. .venv/bin/activate
pip install mcp
python -m safe_ai_util_mcp.server
```

Clients can configure the MCP server with stdio transport and set `COPILOT_AGENT_UTIL_BIN` to the `safe-ai-util` binary path.
