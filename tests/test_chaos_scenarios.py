"""Fast, deterministic unit tests for the chaos layer — no Docker, no live SUT,
so they run in the standard pytest gate. They cover the two things the *method*
relies on being correct:

  1. probe classification + recovery polling (the primitives in faults.py);
  2. the full steady-state → fault → recover scenario flow (scenarios.py),
     driven by an in-memory `Sim` that stands in for the compose stack — so we
     can assert PASS on a well-behaved system AND FAIL on a hanging / traceback-
     leaking / non-recovering one, without ever touching Docker.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import requests

from chaos.faults import ComposeController, ProbeResult, probe, wait_for_recovery
from chaos.latency import Prometheus, Toxiproxy
from chaos.run import EXCLUSIONS, render_markdown
from chaos.scenarios import (
    V1_SCENARIOS,
    ScenarioResult,
    Step,
    scenario_db_latency,
    scenario_db_outage,
    scenario_process_kill,
)

BASE = "http://sut:5000"
NO_SLEEP = lambda _: None  # noqa: E731 - tiny injected stub keeps tests instant


@dataclass
class FakeResp:
    status_code: int
    text: str


@dataclass
class FakeProc:
    """Stands in for a subprocess.CompletedProcess — only `.stdout` is read."""

    stdout: str = ""


class Sim:
    """An in-memory stand-in for the compose stack. Doubles as the
    `ComposeController` runner (mutating state) and the HTTP `get` (reading it)."""

    def __init__(
        self,
        *,
        web_up: bool = True,
        hang_on_db_down: bool = False,
        traceback_on_db_down: bool = False,
        crash_recovers: bool = True,
    ) -> None:
        self.db_paused = False
        self.web_up = web_up
        self.hang_on_db_down = hang_on_db_down
        self.traceback_on_db_down = traceback_on_db_down
        self.crash_recovers = crash_recovers  # does the restart policy bring web back?
        self.restart_count = 0
        self.calls: list[tuple[str, str]] = []  # (verb, service) of state-mutating faults

    # -- ComposeController runner ------------------------------------------------
    def runner(self, cmd: list[str], cwd: Path) -> FakeProc:
        if cmd[:2] == ["docker", "inspect"]:
            return FakeProc(str(self.restart_count))  # `docker inspect --format {{.RestartCount}}`
        verb, service = cmd[2], cmd[-1]
        if verb == "ps":  # `compose ps -q web` -> container id (read-only)
            return FakeProc("web-cid")
        self.calls.append((verb, service))
        if verb == "pause":
            self.db_paused = True
        elif verb == "unpause":
            self.db_paused = False
        elif verb == "kill":
            self.web_up = False
        elif verb == "exec":  # the in-container crash
            self.calls[-1] = ("crash", "web")
            if self.crash_recovers:
                self.restart_count += 1  # restart policy fired; web is back
            else:
                self.web_up = False  # process died and stayed down
        elif verb == "up":
            self.web_up = True
        return FakeProc("")

    def controller(self) -> ComposeController:
        return ComposeController(Path("/sut"), runner=self.runner)

    # -- injected HTTP get -------------------------------------------------------
    def get(self, url: str, timeout: float | None = None) -> FakeResp:
        if not self.web_up:
            raise requests.exceptions.ConnectionError("connection refused")
        if url.endswith("/course"):
            if self.db_paused:
                if self.hang_on_db_down:
                    raise requests.exceptions.ReadTimeout("request hung")
                body = "Traceback (most recent call last):\n  ..." if self.traceback_on_db_down else "Server Error"
                return FakeResp(500, body)
            return FakeResp(200, "<holes>1..18</holes>")
        return FakeResp(200, "<home/>")  # static route — up whenever the process is up


# ── faults.py: probe classification ──────────────────────────────────────────


def test_probe_classifies_ok():
    r = probe(f"{BASE}/course", get=lambda url, timeout: FakeResp(200, "x"))
    assert r.ok and r.reachable and not r.clean_5xx and not r.leaked_traceback


def test_probe_classifies_clean_5xx_without_traceback():
    r = probe(f"{BASE}/course", get=lambda url, timeout: FakeResp(503, "Service Unavailable"))
    assert r.clean_5xx and not r.leaked_traceback and not r.ok


def test_probe_flags_leaked_traceback():
    body = "Traceback (most recent call last):\n  File ..."
    r = probe(f"{BASE}/course", get=lambda url, timeout: FakeResp(500, body))
    assert r.clean_5xx and r.leaked_traceback


def test_probe_distinguishes_refused_from_timeout():
    def refuse(url, timeout):
        raise requests.exceptions.ConnectionError("refused")

    def hang(url, timeout):
        raise requests.exceptions.ReadTimeout("hang")

    refused = probe(BASE, get=refuse)
    timed = probe(BASE, get=hang)
    assert refused.refused and not refused.timed_out and not refused.reachable
    assert timed.timed_out and not timed.refused and not timed.reachable


def test_probe_describe_is_human_readable():
    assert "200" in probe(BASE, get=lambda url, timeout: FakeResp(200, "x")).describe()
    tb = probe(BASE, get=lambda url, timeout: FakeResp(500, "Traceback (most recent call last):"))
    assert "TRACEBACK" in tb.describe()


# ── faults.py: recovery polling ──────────────────────────────────────────────


def test_wait_for_recovery_returns_immediately_when_up():
    r, waited = wait_for_recovery(BASE, get=lambda url, timeout: FakeResp(200, "x"), sleep=NO_SLEEP)
    assert r.ok and waited == 0.0


def test_wait_for_recovery_polls_until_up():
    seq = [FakeResp(500, "down"), FakeResp(500, "down"), FakeResp(200, "up")]

    def flaky(url, timeout):
        return seq.pop(0)

    r, waited = wait_for_recovery(BASE, get=flaky, interval=2.0, timeout=30.0, sleep=NO_SLEEP)
    assert r.ok and waited == 4.0  # two failed polls before success


def test_wait_for_recovery_gives_up_at_timeout():
    def always_down(url, timeout):
        raise requests.exceptions.ConnectionError("refused")

    r, waited = wait_for_recovery(BASE, get=always_down, interval=2.0, timeout=4.0, sleep=NO_SLEEP)
    assert not r.ok and waited >= 4.0


# ── faults.py: compose command construction ──────────────────────────────────


def test_compose_controller_builds_commands():
    captured: list[tuple[list[str], Path]] = []
    ctrl = ComposeController(Path("/sut"), runner=lambda cmd, cwd: captured.append((cmd, cwd)))
    ctrl.pause("db")
    ctrl.unpause("db")
    ctrl.kill("web")
    ctrl.up("web")
    cmds = [cmd for cmd, _ in captured]
    assert cmds == [
        ["docker", "compose", "pause", "db"],
        ["docker", "compose", "unpause", "db"],
        ["docker", "compose", "kill", "web"],
        ["docker", "compose", "up", "-d", "web"],
    ]
    assert all(cwd == Path("/sut") for _, cwd in captured)


def test_compose_controller_crash_signals_pid1_from_inside():
    captured: list[list[str]] = []

    def runner(cmd, cwd):
        captured.append(cmd)
        return FakeProc("")

    ComposeController(Path("/sut"), runner=runner).crash("web")
    # in-container kill of PID 1 — NOT `docker kill` (which the restart policy ignores)
    assert captured[-1] == ["docker", "compose", "exec", "-T", "web", "sh", "-c", "kill -TERM 1"]


def test_restart_count_resolves_container_then_inspects():
    def runner(cmd, cwd):
        if cmd[:2] == ["docker", "inspect"]:
            return FakeProc("4\n")
        if cmd[2] == "ps":
            return FakeProc("abc123\n")
        return FakeProc("")

    assert ComposeController(Path("/sut"), runner=runner).restart_count("web") == 4


def test_restart_count_is_none_when_container_unresolved():
    assert ComposeController(Path("/sut"), runner=lambda cmd, cwd: FakeProc("")).restart_count("web") is None


# ── scenarios.py: DB outage ──────────────────────────────────────────────────


def test_db_outage_passes_on_well_behaved_system():
    sim = Sim()
    r = scenario_db_outage(BASE, sim.controller(), get=sim.get, sleep=NO_SLEEP)
    assert r.status == "passed"
    assert [s.ok for s in r.steps] == [True, True, True, True]
    assert ("pause", "db") in sim.calls and ("unpause", "db") in sim.calls  # fault injected AND cleaned up


def test_db_outage_fails_when_data_route_hangs():
    sim = Sim(hang_on_db_down=True)
    r = scenario_db_outage(BASE, sim.controller(), get=sim.get, sleep=NO_SLEEP)
    assert r.status == "failed"
    degrade = next(s for s in r.steps if "data route" in s.name)
    assert not degrade.ok and "hang" in degrade.observed
    assert ("unpause", "db") in sim.calls  # still restored despite the failure


def test_db_outage_fails_on_leaked_traceback():
    sim = Sim(traceback_on_db_down=True)
    r = scenario_db_outage(BASE, sim.controller(), get=sim.get, sleep=NO_SLEEP)
    assert r.status == "failed"
    degrade = next(s for s in r.steps if "data route" in s.name)
    assert not degrade.ok and "TRACEBACK" in degrade.observed


def test_db_outage_inconclusive_when_sut_not_up():
    sim = Sim(web_up=False)
    r = scenario_db_outage(BASE, sim.controller(), get=sim.get, sleep=NO_SLEEP)
    assert r.status == "inconclusive"
    assert sim.calls == []  # never injected a fault into an already-unhealthy system


# ── scenarios.py: process kill ───────────────────────────────────────────────


def test_process_kill_passes_when_restart_policy_recovers():
    sim = Sim(crash_recovers=True)
    r = scenario_process_kill(BASE, sim.controller(), get=sim.get, restart_timeout=30.0, sleep=NO_SLEEP)
    assert r.status == "passed"
    assert ("crash", "web") in sim.calls  # killed the process from inside, not `docker kill`
    assert ("up", "web") not in sim.calls  # recovery was automatic, no manual intervention
    engaged = next(s for s in r.steps if "RestartCount" in s.expectation)
    assert engaged.ok and "0 → 1" in engaged.observed


def test_process_kill_fails_and_restores_when_no_auto_restart():
    sim = Sim(crash_recovers=False)  # process dies and the restart policy never brings it back
    r = scenario_process_kill(BASE, sim.controller(), get=sim.get, restart_timeout=4.0, sleep=NO_SLEEP)
    assert r.status == "failed"
    assert ("up", "web") in sim.calls  # harness restored the stack after the failure
    assert r.notes


def test_process_kill_inconclusive_when_sut_not_up():
    sim = Sim(web_up=False)
    r = scenario_process_kill(BASE, sim.controller(), get=sim.get, sleep=NO_SLEEP)
    assert r.status == "inconclusive"
    assert sim.calls == []


# ── registry + report ────────────────────────────────────────────────────────


def test_v1_registry_well_formed():
    assert set(V1_SCENARIOS) == {"db-outage", "process-kill"}


def test_render_markdown_has_results_and_scope_sections():
    results = [
        ScenarioResult("DB outage", "below the app", "hyp", status="passed", steps=[Step("s", "e", "o", True)]),
        ScenarioResult("Process kill", "the app itself", "hyp", status="failed", steps=[Step("s", "e", "o", False)]),
    ]
    md = render_markdown({"run_at": "now", "base_url": BASE, "compose_dir": "/sut"}, results)
    assert "1/2 scenarios passed" in md
    assert "DB outage" in md and "Process kill" in md
    assert "Excluded by design" in md and "toxiproxy" in md
    # every exclusion rationale is surfaced in the evidence
    for what, _ in EXCLUSIONS:
        assert what in md


# ── scenarios.py: DB latency (v2 grey failure) ───────────────────────────────


class FakeToxi:
    """Records latency calls; `active` flips so an injected `measure` can report a
    fast baseline vs a slow degraded response."""

    def __init__(self) -> None:
        self.active = False
        self.calls: list[str] = []

    def add_latency(self, latency_ms, **_):
        self.active = True
        self.calls.append(f"add:{latency_ms}")

    def remove_latency(self, **_):
        self.active = False
        self.calls.append("remove")


def _latency_measure(toxi: FakeToxi, *, base: float = 0.05, slow: float = 0.7):
    """An injected measure() returning a 200 whose elapsed depends on toxi state."""

    def measure(url: str) -> ProbeResult:
        return ProbeResult(url, 200, slow if toxi.active else base, body_excerpt="<holes>")

    return measure


class FakeProm:
    def __init__(self, value):
        self._value = value

    def p95(self, **_):
        return self._value


def test_db_latency_passes_when_degrades_and_breach_observed():
    tx = FakeToxi()
    r = scenario_db_latency(
        BASE,
        tx,
        FakeProm(0.62),
        measure=_latency_measure(tx),
        burst=3,
        settle_seconds=0,
        sleep=NO_SLEEP,
        slo_seconds=0.5,
    )
    assert r.status == "passed"
    assert tx.calls == ["add:600", "remove"]  # injected then always lifted
    breach = next(s for s in r.steps if "Prometheus" in s.name)
    assert breach.ok and "620ms" in breach.observed


def test_db_latency_best_effort_when_prometheus_has_no_samples():
    tx = FakeToxi()
    r = scenario_db_latency(
        BASE, tx, FakeProm(None), measure=_latency_measure(tx), burst=3, settle_seconds=0, sleep=NO_SLEEP
    )
    assert r.status == "passed"  # missing p95 does NOT fail the scenario (best-effort)
    breach = next(s for s in r.steps if "Prometheus" in s.name)
    assert breach.ok and "not asserted" in breach.observed


def test_db_latency_fails_when_prometheus_contradicts_degradation():
    tx = FakeToxi()
    # app degraded (slow) but Prometheus shows p95 UNDER the SLO -> a real contradiction
    r = scenario_db_latency(
        BASE,
        tx,
        FakeProm(0.2),
        measure=_latency_measure(tx),
        burst=3,
        settle_seconds=0,
        sleep=NO_SLEEP,
        slo_seconds=0.5,
    )
    assert r.status == "failed"
    breach = next(s for s in r.steps if "Prometheus" in s.name)
    assert not breach.ok


def test_db_latency_fails_when_app_does_not_slow_down():
    tx = FakeToxi()
    # toxic added but the app stays fast (latency not biting) -> degradation step fails
    r = scenario_db_latency(
        BASE, tx, FakeProm(0.62), measure=_latency_measure(tx, slow=0.1), burst=3, settle_seconds=0, sleep=NO_SLEEP
    )
    assert r.status == "failed"
    assert "remove" in tx.calls  # toxic still lifted


def test_db_latency_inconclusive_when_sut_not_up():
    tx = FakeToxi()

    def down(url):
        return ProbeResult(url, None, 0.0, error="ConnectionError")

    r = scenario_db_latency(BASE, tx, FakeProm(0.62), measure=down, burst=3, settle_seconds=0, sleep=NO_SLEEP)
    assert r.status == "inconclusive"
    assert tx.calls == []  # never injected into an unhealthy system


# ── latency.py: Toxiproxy / Prometheus request construction ──────────────────


def test_toxiproxy_add_latency_builds_correct_toxic():
    captured: list[tuple] = []

    def request(method, url, **kw):
        captured.append((method, url, kw.get("json")))
        return FakeProc("")

    Toxiproxy(request=request).add_latency(600)
    method, url, body = captured[-1]
    assert method == "POST" and url.endswith("/proxies/postgres/toxics")
    assert body["type"] == "latency" and body["attributes"]["latency"] == 600


def test_toxiproxy_remove_latency_targets_the_toxic():
    captured: list[tuple] = []
    Toxiproxy(request=lambda m, u, **k: captured.append((m, u)) or FakeProc("")).remove_latency()
    assert captured[-1] == ("DELETE", "http://localhost:8474/proxies/postgres/toxics/latency_down")


def test_prometheus_p95_parses_value_and_handles_empty_and_nan():
    class Resp:
        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    def make(value_rows):
        return lambda url, params, timeout: Resp({"data": {"result": value_rows}})

    hit = Prometheus(get=make([{"value": [123, "0.62"]}]))
    assert hit.p95() == 0.62
    assert Prometheus(get=make([])).p95() is None  # empty result -> no signal
    assert Prometheus(get=make([{"value": [123, "NaN"]}])).p95() is None  # NaN -> no signal
