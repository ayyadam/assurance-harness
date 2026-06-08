"""Unit tests for the security_agent SARIF normaliser (F-033).

Deterministic, no scanner binary and no LLM — so they run in the default
``pytest`` gate. They pin the two behaviours the SARIF path must guarantee:

  - a secret finding is REDACTED — the matched value never reaches a Finding
    field (and so never reaches the committed report);
  - a generic SARIF tool (e.g. CodeQL) is normalised with its message intact.

The end-to-end "does the judge call a real planted secret true_positive" control
is the gated test in ``tests/agents/test_security_secrets_control.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from security_agent.findings import normalize_sarif

_SECRET_VALUE = "AKIAIOSFODNN7EXAMPLE_DO_NOT_LEAK"


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "scan.sarif"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_secret_sarif_is_redacted(tmp_path: Path) -> None:
    sarif = {
        "runs": [
            {
                "tool": {"driver": {"name": "gitleaks"}},
                "results": [
                    {
                        "ruleId": "aws-access-token",
                        "level": "error",
                        "message": {"text": "AWS Access Token detected"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": "app/config.py"},
                                    "region": {"startLine": 12, "snippet": {"text": _SECRET_VALUE}},
                                }
                            }
                        ],
                    }
                ],
            }
        ]
    }
    findings = normalize_sarif(_write(tmp_path, sarif), kind="secret", redact=True)

    assert len(findings) == 1
    f = findings[0]
    assert f.tool == "gitleaks"
    assert f.kind == "secret"
    assert f.rule_id == "aws-access-token"
    assert f.location == "app/config.py:12"
    assert f.severity == "HIGH"
    # The matched value must never appear anywhere on the Finding.
    blob = " ".join([f.title, f.detail, f.location, f.rule_id, f.severity])
    assert _SECRET_VALUE not in blob, "secret value leaked into a Finding field"
    assert "redact" in f.detail.lower()


def test_generic_sarif_keeps_message(tmp_path: Path) -> None:
    sarif = {
        "runs": [
            {
                "tool": {"driver": {"name": "CodeQL"}},
                "results": [
                    {
                        "ruleId": "py/sql-injection",
                        "level": "error",
                        "message": {"text": "This SQL query depends on a user-provided value"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": "app/db.py"},
                                    "region": {"startLine": 40},
                                }
                            }
                        ],
                    }
                ],
            }
        ]
    }
    findings = normalize_sarif(_write(tmp_path, sarif), kind="SAST")

    assert len(findings) == 1
    f = findings[0]
    assert f.tool == "CodeQL"
    assert f.kind == "SAST"
    assert f.rule_id == "py/sql-injection"
    assert f.location == "app/db.py:40"
    assert "SQL query" in f.title


def test_empty_sarif_yields_nothing(tmp_path: Path) -> None:
    assert normalize_sarif(_write(tmp_path, {"runs": []}), kind="secret") == []
