"""Gated unit test for the contract evidence CLI command construction.

No SUT, no network, no Schemathesis run — just asserts the CLI invocation is
built correctly (profile URL, seed, phases, report formats, optional auth)."""

from __future__ import annotations

from pathlib import Path

from contract.evidence import build_command


def test_build_command_includes_url_seed_phases_and_reports():
    cmd = build_command(
        "http://sut:5000/api/v1/openapi.json",
        Path("/tmp/reports"),
        max_examples=20,
        seed=1234,
        phases="fuzzing",
    )
    assert cmd[:3] == ["schemathesis", "run", "http://sut:5000/api/v1/openapi.json"]
    assert "-n" in cmd and cmd[cmd.index("-n") + 1] == "20"
    assert cmd[cmd.index("--seed") + 1] == "1234"
    assert cmd[cmd.index("--phases") + 1] == "fuzzing"
    assert cmd[cmd.index("--report") + 1] == "junit,vcr"
    assert cmd[cmd.index("--report-dir") + 1] == str(Path("/tmp/reports"))
    assert "-H" not in cmd  # no token => no auth header


def test_build_command_adds_auth_header_when_token_present():
    cmd = build_command(
        "http://sut:5000/api/v1/openapi.json",
        Path("/tmp/reports"),
        max_examples=5,
        seed=1,
        phases="fuzzing",
        token="abc.def.ghi",
    )
    assert cmd[cmd.index("-H") + 1] == "Authorization: Bearer abc.def.ghi"
