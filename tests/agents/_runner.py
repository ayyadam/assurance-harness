"""Shared harness: run an agent N times, collect outputs, compute jitter.

Each test case is one (agent_callable, fixture_input). The harness invokes
the callable N times in succession with the same input and returns a list
of N outputs. Jitter helpers reduce a list of outputs to scalar metrics
(most-frequent-top-result, stability-rate, vocab-violation count) that the
tests assert against and the report renderer surfaces.

No LLM in the helpers themselves — jitter analysis is deterministic Python
over the outputs.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


@dataclass
class Run:
    """One invocation of the agent — its output and timing."""

    n: int  # 1-indexed run number
    output: dict[str, Any]  # the agent's structured output, normalised to a dict
    elapsed_s: float
    error: str | None = None  # if the run raised, the message goes here


@dataclass
class CaseResult:
    """All N runs for one (agent, fixture) case."""

    case_id: str
    agent: str  # "risk_agent" | "triage_agent"
    n_runs: int
    runs: list[Run] = field(default_factory=list)

    @property
    def successful_runs(self) -> list[Run]:
        return [r for r in self.runs if r.error is None]

    def to_json(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "agent": self.agent,
            "n_runs": self.n_runs,
            "successful": len(self.successful_runs),
            "runs": [
                {"n": r.n, "elapsed_s": round(r.elapsed_s, 2), "error": r.error, "output": r.output} for r in self.runs
            ],
        }


def run_n_times(
    case_id: str,
    agent: str,
    n: int,
    invoke: Callable[[], dict[str, Any]],
) -> CaseResult:
    """Invoke ``invoke()`` N times sequentially, capturing output + timing per run."""
    result = CaseResult(case_id=case_id, agent=agent, n_runs=n)
    for i in range(1, n + 1):
        started = time.perf_counter()
        try:
            output = invoke()
            err = None
        except Exception as exc:  # noqa: BLE001 — any agent failure is a regression signal
            output = {}
            err = f"{type(exc).__name__}: {exc}"[:300]
        elapsed = time.perf_counter() - started
        result.runs.append(Run(n=i, output=output, elapsed_s=elapsed, error=err))
    return result


# ── jitter metrics ────────────────────────────────────────────────────────


def top_value_stability(outputs: list[dict], extract: Callable[[dict], Any]) -> tuple[Any, float]:
    """Return (mode_value, fraction_of_runs_matching_mode).

    ``extract`` pulls the "top result" from one run's output (e.g. the
    top-ranked R-ID for risk_agent, the category for triage_agent). The
    mode is the most-common extracted value across runs; the fraction
    quantifies stability (1.0 = identical across all runs).
    """
    if not outputs:
        return None, 0.0
    values = [extract(o) for o in outputs]
    counter = Counter(values)
    mode_value, mode_count = counter.most_common(1)[0]
    return mode_value, mode_count / len(values)


def value_presence_rate(outputs: list[dict], extract: Callable[[dict], list], target: Any) -> float:
    """Fraction of runs where ``target`` appears in the extracted list."""
    if not outputs:
        return 0.0
    hits = sum(1 for o in outputs if target in extract(o))
    return hits / len(outputs)


def vocab_violations(values: list[Any], allowed: set[Any]) -> list[Any]:
    """Return values that fall outside the allowed closed vocabulary."""
    return [v for v in values if v not in allowed]


def expected_match_rate(outputs: list[dict], extract: Callable[[dict], Any], expected: Any) -> float:
    """Fraction of runs where the extracted value equals ``expected``.

    Distinct from :func:`top_value_stability` — that measures internal agreement
    (does the agent give the same answer across runs); this measures agreement
    with an external truth (does the agent's stable answer match the golden set).
    A run can have stability=1.0 with expected_match_rate=0.0 — the agent is
    stable, but stably wrong. That divergence is exactly what the v2 v2
    regression suite is built to surface.
    """
    if not outputs:
        return 0.0
    hits = sum(1 for o in outputs if extract(o) == expected)
    return hits / len(outputs)


class StableDivergentWarning(UserWarning):
    """Soft signal: the agent is internally stable but disagrees with the golden truth.

    Raised when the run-set stability is high (agent gives the same answer N times)
    but the answer does NOT match the expected value from the golden set. The hard
    invariants still pass — schema and closed-vocabulary hold — so the test does
    not fail. The warning surfaces the divergence so it does not get buried in
    a 'tests passed' headline. See the case detail in the rendered report.
    """


# ── report writing ────────────────────────────────────────────────────────


def write_report_json(case_results: list[CaseResult], filename: str = "regression-report.json") -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / filename
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "cases": [c.to_json() for c in case_results],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
