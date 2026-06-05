"""Non-blinding regression — the explore_agent judge still fires on a concern.

F-023 reframed ``business_rule_concern`` around *wrongful acceptance* and lifted
the explore_agent v2 v1 eval to 1.000. But that eval's golden set is entirely
``expected`` (the seeded SUT has no defects), so a perfect score cannot, on its
own, distinguish a correctly-sharpened judge from one blinded into rubber-stamping
everything as ``expected``.

This test is the durable positive control. A synthetic probe that SHOULD be a
concern — a past-date booking the API wrongly accepted with ``201`` — is run
through the live judge N times, and the judge must still classify it
``business_rule_concern``. The seeded SUT correctly refuses this (409/422), so it
never appears in a live run; it is fabricated here precisely because the eval's
all-``expected`` surface can never exercise the recall direction.

If a future prompt change blinds the judge, this test goes red — which the
all-``expected`` eval never would. See F-024.

Gated on ``RUN_AGENT_REGRESSION=1`` (one local Ollama call per run) like its
siblings; skipped in the default ``pytest`` run and in CI. Needs Ollama, NOT the
SUT — the probe is built in memory, no HTTP.
"""

from __future__ import annotations

import json

import pytest

from explore_agent.judge import CATEGORIES, SEVERITIES, judge
from explore_agent.probe import Probe, Variant
from explore_agent.spec import Endpoint
from tests.agents._runner import run_n_times, top_value_stability, vocab_violations

N_RUNS = 3
MIN_STABILITY = 0.66


def _past_date_booking_accepted() -> Probe:
    """A POST /bookings that WRONGLY succeeded (201) for a tee time in the past.

    The body proves wrongful acceptance: a confirmed booking on a 2020 date. This
    is the canonical example named in the reframed ``business_rule_concern``
    definition, so it is the sharpest test of whether the judge still fires.
    """
    endpoint = Endpoint(
        method="POST",
        path="/api/v1/tee-times/{tee_time_id}/bookings",
        summary="Book a tee time for the authenticated member",
        operation={
            "responses": {
                "201": {"description": "Created"},
                "409": {"description": "Conflict"},
                "422": {"description": "Validation error"},
            }
        },
        components={},
        global_security=[{"BearerAuth": []}],
    )
    variant = Variant(label="edge", body={"group_size": 1}, rationale="book a tee time in the past")
    body = {
        "id": 7,
        "tee_time_id": 5,
        "tee_time_date": "2020-01-01",
        "member_id": 3,
        "group_size": 1,
        "status": "confirmed",
    }
    return Probe(
        endpoint=endpoint,
        variant=variant,
        request_url="http://localhost:5000/api/v1/tee-times/5/bookings",
        request_method="POST",
        request_body={"group_size": 1},
        status=201,
        latency_ms=12.0,
        response_body=body,
        response_text=json.dumps(body),
        auth_mode="default",
    )


# (case_id, probe_factory, expected_category)
CASES = [
    ("past-date-booking-accepted", _past_date_booking_accepted, "business_rule_concern"),
]


@pytest.mark.parametrize("case_id,probe_factory,expected_category", CASES)
def test_judge_still_fires_on_wrongful_acceptance(
    case_id: str,
    probe_factory,
    expected_category: str,
) -> None:
    def invoke() -> dict:
        finding = judge(probe_factory())
        return {
            "category": finding.category,
            "severity": finding.severity,
            "rationale": finding.rationale,
        }

    result = run_n_times(case_id=case_id, agent="explore_judge", n=N_RUNS, invoke=invoke)

    assert result.successful_runs, f"all {N_RUNS} runs raised for {case_id}"
    assert len(result.successful_runs) == N_RUNS, (
        f"{N_RUNS - len(result.successful_runs)} run(s) raised for {case_id}: "
        f"{[r.error for r in result.runs if r.error]}"
    )

    outputs = [r.output for r in result.successful_runs]

    # HARD — schema + closed vocabulary per run.
    for i, o in enumerate(outputs, start=1):
        assert o.get("category") in CATEGORIES, f"run {i}: category outside enum: {o.get('category')}"
        assert o.get("severity") in SEVERITIES, f"run {i}: severity outside enum: {o.get('severity')}"
        assert isinstance(o.get("rationale"), str) and o["rationale"], f"run {i}: missing rationale"
    cats = [o["category"] for o in outputs]
    assert not vocab_violations(cats, set(CATEGORIES)), f"categories outside enum: {set(cats)}"

    # THE non-blinding invariant — jitter-tolerant (mode + stability floor), mirroring
    # the risk/triage suites' MIN_TOP_STABILITY pattern. A 2/3 fire still passes; a
    # judge that has been blinded into stably answering `expected` fails here.
    mode, stability = top_value_stability(outputs, lambda o: o["category"])
    assert mode == expected_category, (
        f"judge no longer fires `{expected_category}` on a known wrongful-acceptance probe "
        f"— stable mode was `{mode}`. A prompt change may have blinded the agent."
    )
    assert stability >= MIN_STABILITY, (
        f"`{expected_category}` fired only {stability:.0%} of {N_RUNS} runs (mode `{mode}`)."
    )
