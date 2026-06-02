"""Adversarial regression — triage_agent invariants under LLM jitter.

For each cached cluster fixture, run the agent N times and assert:

  - HARD: schema validity per run (category + candidate_risk_id + rationale +
    suggested_action all decode as expected types).
  - HARD: closed-vocabulary — category in {flake, defect, infra, env, unknown};
    R-ID is null or in the live register.
  - SOFT (metric, reported): stability of the emitted category across runs;
    stability of the emitted R-ID across runs; presence rate of the expected
    (category, R-ID).
"""

from __future__ import annotations

import warnings
from collections.abc import Generator
from datetime import UTC, datetime

import pytest

from risk_agent.register import parse_register
from tests.agents._runner import (
    CaseResult,
    StableDivergentWarning,
    expected_match_rate,
    run_n_times,
    top_value_stability,
    vocab_violations,
)
from triage_agent.cluster import Cluster, ClusterMember, categorise
from triage_agent.fetcher import Run
from triage_agent.parser import Failure

N_RUNS = 3
MIN_TOP_STABILITY = 0.66
ALLOWED_CATEGORIES = {"flake", "defect", "infra", "env", "unknown"}


def _synth_run(num: int, sha: str, title: str) -> Run:
    return Run(
        id=10_000 + num,
        number=num,
        workflow_name="Assurance Harness",
        url=f"https://github.com/ayyadam/testing-system/actions/runs/{10_000 + num}",
        event="pull_request",
        branch="feat/example",
        sha=sha,
        title=title,
        conclusion="failure",
        created_at=datetime.now(UTC),
    )


def _synth_cluster_r018() -> Cluster:
    """R-018-shaped flake: Playwright TimeoutError after a navigating click."""
    failure = Failure(
        kind="pytest",
        job_name="Functional Tests (Playwright)",
        test_path="functional/test_booking_assistant.py",
        test_name="test_assistant_interprets_request_and_books_a_slot",
        test_params="",
        error_class="playwright._impl._errors.TimeoutError",
        error_message=("Timeout 30000ms exceeded. Call log: waiting for navigation to /member/dashboard"),
    )
    cluster = Cluster(signature=failure.signature)
    cluster.members.append(
        ClusterMember(
            run=_synth_run(31, "abcdef1", "post-merge dev push after PR #13"),
            failure=failure,
        )
    )
    return cluster


def _synth_cluster_perf() -> Cluster:
    """F-005-shaped defect: k6 threshold breach on the perf gate."""
    failure = Failure(
        kind="step",
        job_name="Performance (k6)",
        test_path="<step>",
        test_name="Performance (k6)::Run k6 load test",
        test_params="",
        error_class="<step-failure>",
        error_message="Process completed with exit code 99 (threshold breach on http_req_duration p95)",
    )
    cluster = Cluster(signature=failure.signature)
    cluster.members.append(
        ClusterMember(
            run=_synth_run(22, "12345ab", "perf threshold breach on tee-times list endpoint"),
            failure=failure,
        )
    )
    return cluster


# (case_id, cluster_factory, expected_category, expected_risk_id)
CASES = [
    ("r-018-timeout-flake", _synth_cluster_r018, "flake", "R-018"),
    ("k6-threshold-defect", _synth_cluster_perf, "defect", "R-007"),
]


@pytest.fixture(scope="session")
def risk_register():
    return parse_register()


@pytest.fixture(scope="session")
def _collected_results() -> Generator[list[CaseResult], None, None]:
    bucket: list[CaseResult] = []
    yield bucket
    if bucket:
        from tests.agents._runner import write_report_json

        write_report_json(bucket, "regression-report-triage.json")


@pytest.mark.parametrize("case_id,cluster_factory,expected_category,expected_rid", CASES)
def test_triage_agent_invariants(
    case_id: str,
    cluster_factory,
    expected_category: str,
    expected_rid: str,
    risk_register,
    _collected_results: list[CaseResult],
) -> None:
    allowed_ids = {r.id for r in risk_register} | {None}

    def invoke() -> dict:
        cluster = cluster_factory()
        categorise(cluster, risk_register)
        return {
            "category": cluster.category,
            "candidate_risk_id": cluster.candidate_risk_id,
            "rationale": cluster.rationale,
            "suggested_action": cluster.suggested_action,
        }

    case_result = run_n_times(case_id=case_id, agent="triage_agent", n=N_RUNS, invoke=invoke)
    _collected_results.append(case_result)

    assert case_result.successful_runs, f"all {N_RUNS} runs failed for {case_id}"
    assert len(case_result.successful_runs) == N_RUNS, (
        f"{N_RUNS - len(case_result.successful_runs)} run(s) raised for {case_id}: "
        f"{[r.error for r in case_result.runs if r.error]}"
    )

    outputs = [r.output for r in case_result.successful_runs]

    # HARD — schema per run.
    for i, o in enumerate(outputs, start=1):
        assert isinstance(o.get("category"), str), f"run {i}: missing category"
        assert isinstance(o.get("rationale"), str) and o["rationale"], f"run {i}: missing rationale"
        assert isinstance(o.get("suggested_action"), str), f"run {i}: missing suggested_action"
        # candidate_risk_id may be None — only assert it's str-or-None.
        rid = o.get("candidate_risk_id")
        assert rid is None or isinstance(rid, str), f"run {i}: candidate_risk_id wrong type"

    # HARD — closed-vocab category + R-ID.
    cats = [o["category"] for o in outputs]
    bad_cats = vocab_violations(cats, ALLOWED_CATEGORIES)
    assert not bad_cats, f"emitted categories outside the closed enum: {set(bad_cats)}"

    rids = [o.get("candidate_risk_id") for o in outputs]
    bad_rids = vocab_violations(rids, allowed_ids)
    assert not bad_rids, f"emitted R-IDs outside register∪{{null}}: {set(bad_rids)}"

    # SOFT — stability metrics.
    cat_mode, cat_stability = top_value_stability(outputs, lambda o: o["category"])
    rid_mode, rid_stability = top_value_stability(outputs, lambda o: o.get("candidate_risk_id"))
    cat_match = expected_match_rate(outputs, lambda o: o["category"], expected_category)
    rid_match = expected_match_rate(outputs, lambda o: o.get("candidate_risk_id"), expected_rid)
    is_divergent = (cat_stability >= MIN_TOP_STABILITY and cat_match < MIN_TOP_STABILITY) or (
        rid_stability >= MIN_TOP_STABILITY and rid_match < MIN_TOP_STABILITY
    )

    case_result.runs[-1].output["_metrics"] = {
        "category_mode": cat_mode,
        "category_stability": round(cat_stability, 3),
        "category_match_rate": round(cat_match, 3),
        "rid_mode": rid_mode,
        "rid_stability": round(rid_stability, 3),
        "rid_match_rate": round(rid_match, 3),
        "expected_category_match": cat_mode == expected_category,
        "expected_rid_match": rid_mode == expected_rid,
        "stable_divergent": is_divergent,
    }

    assert cat_stability >= MIN_TOP_STABILITY, (
        f"category flapped across runs: mode={cat_mode} stability={cat_stability:.2f}"
    )
    assert rid_stability >= MIN_TOP_STABILITY, (
        f"R-ID flapped across runs: mode={rid_mode} stability={rid_stability:.2f}"
    )
    # SOFT — stable-divergent warning, not failure. See risk_agent test for the rationale.
    if is_divergent:
        parts = []
        if cat_match < MIN_TOP_STABILITY:
            parts.append(f"category mode=`{cat_mode}` (expected `{expected_category}`, match {cat_match:.0%})")
        if rid_match < MIN_TOP_STABILITY:
            parts.append(f"R-ID mode=`{rid_mode}` (expected `{expected_rid}`, match {rid_match:.0%})")
        warnings.warn(
            StableDivergentWarning(
                f"{case_id}: stably divergent from golden set — {'; '.join(parts)}. "
                f"Hard invariants held — this is a prompt or golden-set divergence, "
                f"not a regression failure."
            ),
            stacklevel=2,
        )
