"""The chaos scenarios — one per distinct failure *axis* (scope discipline).

Each scenario is a *steady-state hypothesis*: the system is healthy → we inject
one fault → we assert it degrades within a stated bound AND returns to steady
state on its own. A scenario only injects a fault once its precondition holds; if
the SUT isn't healthy to begin with it reports `inconclusive` rather than blaming
the system for a resilience failure it never had a chance to fail.

v1 (here) — pure `docker`/`compose`, no extra moving parts:
  - `scenario_db_outage`     — axis: dependency *gone*   (below the app)
  - `scenario_process_kill`  — axis: the app *process* dies
v2 — the grey-failure axis (dependency *slow*) via toxiproxy latency.

Deliberately excluded (and why) is documented in run.py's report so the *shape*
of the testing — representative-per-axis, not every permutation — is part of the
evidence.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .faults import ComposeController, probe, wait_for_recovery

DEFAULT_RECOVERY_TIMEOUT = 30.0  # db unpause should recover fast
DEFAULT_RESTART_TIMEOUT = 60.0  # container restart policy needs more headroom


@dataclass
class Step:
    """One assertion within a scenario: what we expected vs what we observed."""

    name: str
    expectation: str
    observed: str
    ok: bool


@dataclass
class ScenarioResult:
    name: str
    axis: str
    hypothesis: str
    status: str = "passed"  # "passed" | "failed" | "inconclusive"
    steps: list[Step] = field(default_factory=list)
    notes: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def _finalise(self) -> ScenarioResult:
        if self.status != "inconclusive":
            self.status = "passed" if all(s.ok for s in self.steps) else "failed"
        return self


def _inconclusive(name: str, axis: str, hypothesis: str, why: str) -> ScenarioResult:
    return ScenarioResult(name, axis, hypothesis, status="inconclusive", notes=why)


# ── scenario 1 — dependency gone (graceful degradation + recovery) ────────────


def scenario_db_outage(
    base_url: str,
    controller: ComposeController,
    *,
    get: Callable | None = None,
    probe_timeout: float = 10.0,
    recovery_timeout: float = DEFAULT_RECOVERY_TIMEOUT,
    sleep: Callable[[float], None] = time.sleep,
) -> ScenarioResult:
    """Pause Postgres mid-flight. A DB-backed route must fail *fast and clean*
    (a 5xx within the timeout, no leaked traceback) while a static route stays
    up — and the app must recover on its own when the DB returns."""
    name, axis = "DB outage", "below the app — dependency gone"
    hypothesis = (
        "With Postgres paused, /course fails fast with a clean 5xx (no traceback), / stays 200, "
        "and the app recovers automatically on unpause."
    )
    course, home = f"{base_url}/course", f"{base_url}/"

    pre = probe(course, timeout=probe_timeout, get=get)
    if not pre.ok:
        return _inconclusive(
            name, axis, hypothesis, f"DB-backed /course was {pre.describe()} before the fault — is the SUT up/seeded?"
        )

    result = ScenarioResult(name, axis, hypothesis)
    result.steps.append(Step("steady state", "/course == 200 before fault", pre.describe(), True))

    try:
        controller.pause("db")
        during = probe(course, timeout=probe_timeout, get=get)
        result.steps.append(
            Step(
                "degrade — data route fails fast",
                "/course returns a clean 5xx within timeout, no leaked traceback",
                during.describe(),
                during.clean_5xx and not during.leaked_traceback,
            )
        )
        static = probe(home, timeout=probe_timeout, get=get)
        result.steps.append(
            Step(
                "partial availability — static route",
                "/ stays 200 while the DB is down (graceful degradation, not total outage)",
                static.describe(),
                static.ok,
            )
        )
    finally:
        controller.unpause("db")  # always restore, even if an assertion above raised

    rec, waited = wait_for_recovery(course, get=get, timeout=recovery_timeout, sleep=sleep, probe_timeout=probe_timeout)
    result.steps.append(
        Step(
            "auto-recovery",
            f"/course returns to 200 within {recovery_timeout:.0f}s of unpause, no manual restart",
            f"{rec.describe()} after ~{waited:.0f}s",
            rec.ok,
        )
    )
    return result._finalise()


# ── scenario 2 — app process dies (auto-restart + clean reconnect) ────────────


def scenario_process_kill(
    base_url: str,
    controller: ComposeController,
    *,
    get: Callable | None = None,
    probe_timeout: float = 10.0,
    restart_timeout: float = DEFAULT_RESTART_TIMEOUT,
    sleep: Callable[[float], None] = time.sleep,
) -> ScenarioResult:
    """Kill the web app's process so the container exits on its own. The
    `restart: unless-stopped` policy must bring it back to 200 with no manual
    intervention (proven by an incremented RestartCount), and the data route must
    serve consistent data afterwards (the connection pool re-established cleanly).

    The fault is an *in-container* process kill, not `docker kill`: Docker treats
    `kill`/`compose kill` as operator stops the restart policy ignores, so killing
    the container would test the wrong thing — see the report notes."""
    name, axis = "Process kill", "the app itself — process death"
    hypothesis = (
        "When the web process dies, the restart policy returns /course to 200 with no manual "
        "intervention (RestartCount increments), and data reads stay consistent."
    )
    course = f"{base_url}/course"

    pre = probe(course, timeout=probe_timeout, get=get)
    if not pre.ok:
        return _inconclusive(
            name, axis, hypothesis, f"/course was {pre.describe()} before the fault — is the SUT up and seeded?"
        )

    result = ScenarioResult(name, axis, hypothesis)
    rc_before = controller.restart_count("web")
    result.steps.append(Step("steady state", "/course == 200 before fault", pre.describe(), True))

    controller.crash("web")  # signal the app's PID 1 from inside -> spontaneous container exit

    rec, waited = wait_for_recovery(course, get=get, timeout=restart_timeout, sleep=sleep, probe_timeout=probe_timeout)
    result.steps.append(
        Step(
            "auto-restart recovery",
            f"restart policy returns /course to 200 within {restart_timeout:.0f}s, no manual intervention",
            f"{rec.describe()} after ~{waited:.0f}s",
            rec.ok,
        )
    )

    rc_after = controller.restart_count("web")
    restarted = rc_before is not None and rc_after is not None and rc_after > rc_before
    result.steps.append(
        Step(
            "restart policy engaged",
            "container RestartCount increments — recovery was the policy, not a coincidence",
            f"RestartCount {rc_before} → {rc_after}",
            restarted,
        )
    )

    if rec.ok:
        after = probe(course, timeout=probe_timeout, get=get)
        result.steps.append(
            Step(
                "clean DB reconnect",
                "data route serves consistent data after restart (pool re-established)",
                after.describe(),
                after.ok,
            )
        )
    else:
        controller.up("web")  # recovery failed — bring it back so we don't leave the stack down
        result.notes = (
            "restart policy did not recover web within budget; harness issued 'compose up' to restore the stack."
        )

    return result._finalise()


V1_SCENARIOS: dict[str, Callable[..., ScenarioResult]] = {
    "db-outage": scenario_db_outage,
    "process-kill": scenario_process_kill,
}
