"""Adversarial regression — risk_agent invariants under LLM jitter.

For each cached PR diff fixture, run the agent N times and assert:

  - HARD: schema validity per run (the structured output decodes and has the
    expected keys/types).
  - HARD: closed-vocabulary — every emitted risk id is in the live register;
    every relevance is 2 or 3 (the v2 v1 prompt change forbids 0 and 1).
  - SOFT (metric, reported): top-ranked R-ID stability across runs;
    presence-rate of the expected top R-ID across runs.

The soft metrics are exposed in the regression report; the test asserts a
loose lower bound on stability so a catastrophic drop (e.g. swap models and
the closed-vocab enum stops working) fails CI-equivalent local checks.
"""

from __future__ import annotations

import warnings
from collections.abc import Generator
from pathlib import Path

import pytest

from risk_agent.agent import prioritise
from risk_agent.diff import DiffBundle
from risk_agent.register import parse_register
from tests.agents._runner import (
    CaseResult,
    StableDivergentWarning,
    expected_match_rate,
    run_n_times,
    top_value_stability,
    value_presence_rate,
    vocab_violations,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
N_RUNS = 3
MIN_TOP_STABILITY = 0.66  # at least 2/3 runs must agree on the top-ranked id

# (case_id, fixture_filename, title, expected_top_id)
CASES = [
    ("pr-7-a11y", "risk_pr-7.diff", "Fix WCAG 2.1 AA accessibility violations on dark theme", "R-008"),
    (
        "pr-12-f008",
        "risk_pr-12.diff",
        "Add time-of-day constraints to the booking assistant (F-008)",
        "R-011",
    ),
]


@pytest.fixture(scope="session")
def risk_register():
    """Parse the live register once per session — input shared across all cases."""
    return parse_register()


@pytest.fixture(scope="session")
def _collected_results() -> Generator[list[CaseResult], None, None]:
    """Collect all CaseResults at session end so the report captures both cases."""
    bucket: list[CaseResult] = []
    yield bucket
    if bucket:
        from tests.agents._runner import write_report_json

        write_report_json(bucket, "regression-report-risk.json")


@pytest.mark.parametrize("case_id,fixture,title,expected_top", CASES)
def test_risk_agent_invariants(
    case_id: str,
    fixture: str,
    title: str,
    expected_top: str,
    risk_register,
    _collected_results: list[CaseResult],
) -> None:
    """Run the agent N times against a cached PR diff and assert invariants."""
    diff_text = (FIXTURES_DIR / fixture).read_text(encoding="utf-8")
    from risk_agent.diff import _bundle  # private helper is the right tool here

    bundle: DiffBundle = _bundle(diff_text, max_lines=800)
    bundle.repo = "ayyadam/golf-web-app"
    bundle.pr_number = int(case_id.split("-")[1])
    bundle.title = title

    allowed_ids = {r.id for r in risk_register}
    allowed_relevance = {2, 3}

    def invoke() -> dict:
        result = prioritise(risk_register, bundle)
        return result.to_json()

    case_result = run_n_times(case_id=case_id, agent="risk_agent", n=N_RUNS, invoke=invoke)
    _collected_results.append(case_result)

    # HARD — every run must have completed.
    assert case_result.successful_runs, f"all {N_RUNS} runs failed for {case_id}"
    assert len(case_result.successful_runs) == N_RUNS, (
        f"{N_RUNS - len(case_result.successful_runs)} run(s) raised for {case_id}: "
        f"{[r.error for r in case_result.runs if r.error]}"
    )

    outputs = [r.output for r in case_result.successful_runs]

    # HARD — schema shape per run.
    for i, o in enumerate(outputs, start=1):
        assert isinstance(o.get("summary"), str), f"run {i}: missing/typewrong summary"
        assert isinstance(o.get("ranked_risks"), list), f"run {i}: ranked_risks not a list"
        assert isinstance(o.get("exploratory_probes"), list), f"run {i}: exploratory_probes not a list"

    # HARD — closed vocabulary on R-IDs.
    all_emitted_ids: list[str] = []
    for o in outputs:
        all_emitted_ids.extend(r["id"] for r in o["ranked_risks"])
    bad_ids = vocab_violations(all_emitted_ids, allowed_ids)
    assert not bad_ids, f"emitted R-IDs outside the register: {set(bad_ids)}"

    # HARD — relevance bounds (v2 v1 prompt forbids 0/1; only 2/3 allowed).
    all_relevances: list[int] = []
    for o in outputs:
        all_relevances.extend(r["relevance"] for r in o["ranked_risks"])
    bad_rel = vocab_violations(all_relevances, allowed_relevance)
    assert not bad_rel, f"relevance values outside {{2,3}}: {bad_rel}"

    # SOFT — stability of the top-ranked R-ID.
    def _top_id(o: dict) -> str | None:
        rr = o.get("ranked_risks") or []
        return rr[0]["id"] if rr else None

    mode_id, stability = top_value_stability(outputs, _top_id)
    presence = value_presence_rate(
        outputs, extract=lambda o: [r["id"] for r in o.get("ranked_risks", [])], target=expected_top
    )
    top_match = expected_match_rate(outputs, _top_id, expected_top)
    is_divergent = stability >= MIN_TOP_STABILITY and top_match < MIN_TOP_STABILITY

    # Surface metrics for the report by tucking them on the last run object.
    case_result.runs[-1].output["_metrics"] = {
        "top_value_mode": mode_id,
        "top_value_stability": round(stability, 3),
        "expected_top_presence_rate": round(presence, 3),
        "expected_top_match_rate": round(top_match, 3),
        "stable_divergent": is_divergent,
    }

    assert stability >= MIN_TOP_STABILITY, (
        f"top-ranked R-ID flapped across runs: mode={mode_id} stability={stability:.2f} < {MIN_TOP_STABILITY:.2f}"
    )
    assert presence >= MIN_TOP_STABILITY, (
        f"expected top R-ID {expected_top} appeared in only {presence:.0%} of runs (< {MIN_TOP_STABILITY:.0%})"
    )
    # SOFT — stable-divergent warning, not failure.
    # The agent is internally consistent (stability ≥ floor) but disagrees with
    # the golden set on the top-1 ranking. Hard invariants pass; the warning
    # surfaces the divergence so it is visible in the test output and not just
    # the report. See StableDivergentWarning for the rationale.
    if is_divergent:
        warnings.warn(
            StableDivergentWarning(
                f"{case_id}: agent stably ranked `{mode_id}` top in "
                f"{int(stability * N_RUNS)}/{N_RUNS} runs but golden set expects `{expected_top}` "
                f"(top-match rate: {top_match:.0%}). Hard invariants held — this is a "
                f"prompt or golden-set divergence, not a regression failure."
            ),
            stacklevel=2,
        )
