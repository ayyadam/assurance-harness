"""dead_end regression — the UI step judge keys off the executor's `succeeded` flag.

F-027. Phase A measured the bug: the judge tagged a SUCCESSFUL intermediate
``fill #password`` (which correctly stays on ``/auth/login``) as ``dead_end``,
inferring "stuck" from the unchanged URL and overriding the executor's
``succeeded=true``. Anchoring ``succeeded`` inside the category text alone did not
move the model (it grades the step against the whole tour goal); the effective fix
was a ``succeeded``-first decision procedure plus an explicit "judge THIS step, not
the whole tour" rule, which flipped the case to ``expected`` 5/5 while a genuine
failed click stayed ``dead_end``.

This is the durable guard, mirroring ``test_explore_judge_nonblinding.py`` (F-024).
Two synthetic ``StepResult``s are run through the live judge N times:

  - a SUCCESSFUL intermediate fill MUST NOT be ``dead_end`` (it is ``expected``);
  - a FAILED click on a missing selector MUST stay ``dead_end``.

Guarding both directions catches a regression that re-introduces the false-positive
*and* one that over-corrects so ``dead_end`` never fires again.

Gated on ``RUN_AGENT_REGRESSION=1`` (one local Ollama call per run) like its
siblings; skipped in the default ``pytest`` run and in CI. Needs Ollama, NOT the
SUT — the steps are built in memory.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from explore_agent.tours import get_tour
from explore_agent.ui_judge import CATEGORIES, SEVERITIES, judge_step
from explore_agent.ui_probe import Step, StepResult
from tests.agents._runner import run_n_times, top_value_stability, vocab_violations

N_RUNS = 3
MIN_STABILITY = 0.66

_LOGIN_ELEMENTS = [
    'a "Home" -> /',
    'a "The Course" -> /course',
    'a "Membership" -> /membership',
    'a "Contact" -> /contact',
    'a "Login" -> /auth/login',
    'input#username "username"',
    'input#password "password"',
    'button#sign-in-button "Sign In"',
]

_COURSE_ELEMENTS = [
    'a "Home" -> /',
    'a "The Course" -> /course',
    'a "Scorecard" -> /course/scorecard',
    'a "Membership" -> /membership',
    'a "Contact" -> /contact',
    'a "Login" -> /auth/login',
]


def _result(step: Step, *, succeeded: bool, url: str, title: str, error: str | None, elements: list[str]) -> StepResult:
    return StepResult(
        step=step,
        started_at=datetime.now(UTC),
        succeeded=succeeded,
        error_message=error,
        page_url=url,
        page_title=title,
        interactive_elements=elements,
        console_errors=[],
        network_5xx=[],
        screenshot_path=None,
        elapsed_ms=5.0,
    )


def _successful_intermediate_fill() -> tuple:
    """A SUCCESSFUL fill #password that correctly stays on /auth/login (F-027's FP)."""
    step = Step(
        "fill",
        "#password",
        "Password1",
        "Filling in the password field with the seed credentials advances towards logging in.",
    )
    result = _result(
        step,
        succeeded=True,
        url="http://localhost:5000/auth/login",
        title="Login — Adam's Golf Club",
        error=None,
        elements=_LOGIN_ELEMENTS,
    )
    return get_tour("member-login-dashboard"), result


def _failed_click_missing_selector() -> tuple:
    """A FAILED click whose selector was never found — a genuine dead_end."""
    step = Step("click", "#explore-course-link", None, "Click through to explore the course in more detail.")
    result = _result(
        step,
        succeeded=False,
        url="http://localhost:5000/course",
        title="The Course — Adam's Golf Club",
        error='Page.click: Timeout 10000ms exceeded.\nCall log:\n  - waiting for locator("#explore-course-link")',
        elements=_COURSE_ELEMENTS,
    )
    return get_tour("public-pages"), result


# (case_id, fixture_factory, expected_category)
CASES = [
    ("successful-intermediate-fill", _successful_intermediate_fill, "expected"),
    ("failed-click-missing-selector", _failed_click_missing_selector, "dead_end"),
]


@pytest.mark.parametrize("case_id,fixture_factory,expected_category", CASES)
def test_ui_judge_keys_dead_end_on_succeeded(
    case_id: str,
    fixture_factory,
    expected_category: str,
) -> None:
    tour, result = fixture_factory()

    def invoke() -> dict:
        finding = judge_step(tour, result)
        return {
            "category": finding.category,
            "severity": finding.severity,
            "rationale": finding.rationale,
        }

    run = run_n_times(case_id=case_id, agent="ui_judge", n=N_RUNS, invoke=invoke)

    assert run.successful_runs, f"all {N_RUNS} runs raised for {case_id}"
    assert len(run.successful_runs) == N_RUNS, (
        f"{N_RUNS - len(run.successful_runs)} run(s) raised for {case_id}: {[r.error for r in run.runs if r.error]}"
    )

    outputs = [r.output for r in run.successful_runs]

    # HARD — schema + closed vocabulary per run.
    for i, o in enumerate(outputs, start=1):
        assert o.get("category") in CATEGORIES, f"run {i}: category outside enum: {o.get('category')}"
        assert o.get("severity") in SEVERITIES, f"run {i}: severity outside enum: {o.get('severity')}"
        assert isinstance(o.get("rationale"), str) and o["rationale"], f"run {i}: missing rationale"
    cats = [o["category"] for o in outputs]
    assert not vocab_violations(cats, set(CATEGORIES)), f"categories outside enum: {set(cats)}"

    # THE F-027 invariant — jitter-tolerant (mode + stability floor), mirroring the
    # risk/triage/non-blinding suites. dead_end must track the `succeeded` flag, not an
    # inferred URL change: a successful intermediate step is `expected`; a failed action
    # stays `dead_end`.
    mode, stability = top_value_stability(outputs, lambda o: o["category"])
    assert mode == expected_category, (
        f"{case_id}: UI judge's stable category was `{mode}`, expected `{expected_category}`. "
        f"F-027 may have regressed — `dead_end` must key off the executor's succeeded flag, "
        f"not an inferred URL change."
    )
    assert stability >= MIN_STABILITY, (
        f"{case_id}: `{expected_category}` was only {stability:.0%} stable over {N_RUNS} runs (mode `{mode}`)."
    )
