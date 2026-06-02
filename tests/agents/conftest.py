"""Opt-in gate for the agent regression suite.

These tests call a local Ollama model 3+ times per case. That is slow
(~30-60s per call) and depends on a running Ollama daemon. We do NOT want
this in the default `pytest` run or the CI gate. Gate via env var.
"""

from __future__ import annotations

import os

import pytest

RUN_FLAG = "RUN_AGENT_REGRESSION"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip every test in tests/agents/ unless RUN_AGENT_REGRESSION=1."""
    if os.environ.get(RUN_FLAG) == "1":
        return
    skip = pytest.mark.skip(reason=f"set {RUN_FLAG}=1 to run agent regression tests")
    for item in items:
        if "tests/agents" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip)
