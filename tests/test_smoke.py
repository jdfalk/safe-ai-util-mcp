#!/usr/bin/env python3
# file: tests/test_smoke.py
# version: 1.0.0
# guid: 7b8e9c10-2d3f-4c51-bf61-0167e2a3d4f5

import importlib


def test_import_server():
    mod = importlib.import_module("safe_ai_util_mcp.server")
    assert hasattr(mod, "build_server")


def test_import_tools():
    mod = importlib.import_module("safe_ai_util_mcp.tools")
    assert hasattr(mod, "get_default_binary")
