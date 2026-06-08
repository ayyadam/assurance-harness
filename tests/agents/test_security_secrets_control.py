"""Positive control — the security_agent judge discriminates real secrets (F-033).

The live repo is clean of secrets (gitleaks finds nothing), so the eval's live
surface can never exercise the secrets-judgement path. This is the durable
positive control, mirroring the explore_agent non-blinding control (F-024):

  - a secret in APPLICATION code (app/config.py) must be judged `true_positive`
    -> `remediate`;
  - the same rule firing in a TEST FIXTURE path must be judged `false_positive`
    -> `accept`.

Both are fed through the real SARIF normaliser (redacting the value) and the real
judge. If a prompt change blinds the judge — rubber-stamping every secret as real,
or dismissing real ones — this goes red where the clean-surface eval never would.

The secret VALUE is never placed in the SARIF here either (the normaliser redacts,
and the judge only ever sees the rule id + path) — so nothing trips the CI secret
gate. Gated on ``RUN_AGENT_REGRESSION=1`` (Ollama calls); needs no scanner binary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from risk_agent.register import parse_register
from security_agent.findings import normalize_sarif
from security_agent.judge import judge
from tests.agents._runner import run_n_times, top_value_stability, vocab_violations

N_RUNS = 3
MIN_STABILITY = 0.66
VERDICTS = {"true_positive", "false_positive", "expected_by_design"}
DISPOSITIONS = {"remediate", "allowlist", "accept"}


def _secret_sarif(uri: str) -> dict:
    """A gitleaks-shaped SARIF result for an AWS key at ``uri`` (value not included)."""
    return {
        "runs": [
            {
                "tool": {"driver": {"name": "gitleaks"}},
                "results": [
                    {
                        "ruleId": "aws-access-token",
                        "level": "error",
                        "message": {"text": "AWS Access Token detected"},
                        "locations": [
                            {"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": 14}}}
                        ],
                    }
                ],
            }
        ]
    }


# (case_id, file path the secret was found at, expected verdict)
CASES = [
    ("secret-in-app-config", "app/config.py", "true_positive"),
    ("secret-in-test-fixture", "tests/fixtures/sample_response.py", "false_positive"),
]


@pytest.mark.parametrize("case_id,uri,expected_verdict", CASES)
def test_judge_discriminates_secret_by_path(case_id: str, uri: str, expected_verdict: str, tmp_path: Path) -> None:
    risks = parse_register()
    sarif_path = tmp_path / f"{case_id}.sarif"
    sarif_path.write_text(json.dumps(_secret_sarif(uri)), encoding="utf-8")

    def invoke() -> dict:
        findings = normalize_sarif(sarif_path, kind="secret", redact=True)
        assert findings, "SARIF normaliser produced no secret finding"
        f = findings[0]
        judge(f, risks)
        return {"verdict": f.verdict, "disposition": f.disposition, "rationale": f.rationale}

    result = run_n_times(case_id=case_id, agent="security_judge", n=N_RUNS, invoke=invoke)

    assert len(result.successful_runs) == N_RUNS, (
        f"{N_RUNS - len(result.successful_runs)} run(s) raised for {case_id}: "
        f"{[r.error for r in result.runs if r.error]}"
    )
    outputs = [r.output for r in result.successful_runs]

    # HARD — closed vocabulary per run.
    for i, o in enumerate(outputs, start=1):
        assert o.get("verdict") in VERDICTS, f"run {i}: verdict outside enum: {o.get('verdict')}"
        assert o.get("disposition") in DISPOSITIONS, f"run {i}: disposition outside enum: {o.get('disposition')}"
        assert isinstance(o.get("rationale"), str) and o["rationale"], f"run {i}: missing rationale"
    assert not vocab_violations([o["verdict"] for o in outputs], VERDICTS)

    # THE control — jitter-tolerant mode + stability floor on the verdict.
    mode, stability = top_value_stability(outputs, lambda o: o["verdict"])
    assert mode == expected_verdict, (
        f"judge no longer calls a secret in `{uri}` `{expected_verdict}` — stable mode was `{mode}`. "
        "A prompt change may have blinded the secrets path."
    )
    assert stability >= MIN_STABILITY, (
        f"`{expected_verdict}` held only {stability:.0%} of {N_RUNS} runs (mode `{mode}`) for {case_id}."
    )
