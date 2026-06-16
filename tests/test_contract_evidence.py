"""Gated unit tests for the contract gate + evidence CLI.

No SUT, no network, no real Schemathesis run — assert the CLI invocation is built
correctly (profile URL, seed, phases, report formats, optional auth, optional
config file) and that ``main`` gates on the child's exit code (and abstains under
``--advisory``). The subprocess and token fetch are stubbed."""

from __future__ import annotations

from pathlib import Path

import contract.evidence as ev
from contract.evidence import build_command


def test_build_command_includes_url_seed_phases_and_reports():
    cmd = build_command(
        "http://sut:5000/api/v1/openapi.json",
        Path("/tmp/reports"),
        max_examples=20,
        seed=1234,
        phases="fuzzing,stateful",
    )
    assert cmd[:3] == ["schemathesis", "run", "http://sut:5000/api/v1/openapi.json"]
    assert "-n" in cmd and cmd[cmd.index("-n") + 1] == "20"
    assert cmd[cmd.index("--seed") + 1] == "1234"
    assert cmd[cmd.index("--phases") + 1] == "fuzzing,stateful"
    assert cmd[cmd.index("--report") + 1] == "junit,vcr,ndjson"
    assert cmd[cmd.index("--report-dir") + 1] == str(Path("/tmp/reports"))
    # health checks are generation-quality, not contract conformance — suppressed
    assert cmd[cmd.index("--suppress-health-check") + 1] == "all"
    assert "-H" not in cmd  # no token => no auth header
    assert "--config-file" not in cmd  # none given => not added


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


def test_build_command_config_file_precedes_run_subcommand():
    cmd = build_command(
        "http://sut:5000/api/v1/openapi.json",
        Path("/tmp/reports"),
        max_examples=5,
        seed=1,
        phases="fuzzing,stateful",
        config_path=Path("/repo/schemathesis.toml"),
    )
    # --config-file is a top-level option: it must come before `run`.
    assert cmd[:4] == ["schemathesis", "--config-file", str(Path("/repo/schemathesis.toml")), "run"]


class _FakeProc:
    def __init__(self, returncode: int):
        self.returncode = returncode
        self.stdout = "fake schemathesis output"
        self.stderr = ""


def _stub_run(monkeypatch, returncode: int):
    monkeypatch.setattr(ev, "fetch_token", lambda profile: None)
    monkeypatch.setattr(ev.subprocess, "run", lambda *a, **k: _FakeProc(returncode))


def test_main_gates_on_schemathesis_exit_code(monkeypatch, tmp_path):
    _stub_run(monkeypatch, returncode=1)
    assert ev.main(["--report-dir", str(tmp_path)]) == 1


def test_main_passes_through_success_exit_code(monkeypatch, tmp_path):
    _stub_run(monkeypatch, returncode=0)
    assert ev.main(["--report-dir", str(tmp_path)]) == 0


def test_main_advisory_always_returns_zero(monkeypatch, tmp_path):
    _stub_run(monkeypatch, returncode=1)
    assert ev.main(["--report-dir", str(tmp_path), "--advisory"]) == 0
