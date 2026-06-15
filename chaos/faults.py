"""Fault-injection primitives + HTTP probing for the chaos layer.

Everything here is dependency-injectable (the HTTP `get` and the compose `runner`
are parameters) so the scenario *logic* in `scenarios.py` can be unit-tested with
fakes — no Docker, no live SUT, so the tests run in the standard pytest gate.

Two ideas only:
  - `probe()` turns one HTTP GET into a `ProbeResult` that distinguishes the
    states a resilience test cares about: 200, a clean 5xx, a *hang* (timeout),
    and connection *refused* (process down). A leaked traceback is flagged
    separately — a clean 5xx that dumps a stack trace is NOT graceful.
  - `ComposeController` is a thin, testable wrapper over `docker compose
    pause|unpause|kill|up <service>` against a given compose directory.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

try:  # requests is a dev dependency; keep import-time failure friendly for tooling
    import requests
except ImportError:  # pragma: no cover - requests is always present in the gate
    requests = None  # type: ignore[assignment]

DEFAULT_PROBE_TIMEOUT = 10.0  # a request taking longer than this is a "hang"
TRACEBACK_MARKER = "Traceback (most recent call last)"


@dataclass
class ProbeResult:
    """The outcome of a single HTTP GET, classified for resilience assertions."""

    url: str
    status: int | None  # None => the request never produced an HTTP response
    elapsed: float
    body_excerpt: str = ""
    error: str | None = None  # exception class name when status is None

    @property
    def reachable(self) -> bool:
        return self.status is not None

    @property
    def ok(self) -> bool:
        return self.status == 200

    @property
    def clean_5xx(self) -> bool:
        """A server error that *was returned* (not a hang) — i.e. failed fast."""
        return self.status is not None and 500 <= self.status < 600

    @property
    def leaked_traceback(self) -> bool:
        return TRACEBACK_MARKER in self.body_excerpt

    @property
    def timed_out(self) -> bool:
        """No response because the request hung (process up but blocked/slow)."""
        return self.status is None and self.error is not None and "Timeout" in self.error

    @property
    def refused(self) -> bool:
        """No response because the connection was refused (process down)."""
        return self.status is None and not self.timed_out

    def describe(self) -> str:
        if self.reachable:
            tag = f"HTTP {self.status}"
            return f"{tag} (TRACEBACK LEAKED)" if self.leaked_traceback else tag
        return "hang/timeout" if self.timed_out else "connection refused"


def probe(
    url: str,
    *,
    timeout: float = DEFAULT_PROBE_TIMEOUT,
    get: Callable | None = None,
) -> ProbeResult:
    """GET `url`, returning a classified `ProbeResult`. Never raises for network
    failures — a refused connection or a timeout is data, not an error."""
    get = get or (requests.get if requests else None)
    if get is None:  # pragma: no cover
        raise RuntimeError("requests is not installed and no `get` was injected")
    start = time.perf_counter()
    try:
        resp = get(url, timeout=timeout)
        return ProbeResult(url, resp.status_code, time.perf_counter() - start, body_excerpt=resp.text[:2000])
    except Exception as exc:  # noqa: BLE001 - any network failure is a probe outcome
        return ProbeResult(url, None, time.perf_counter() - start, error=type(exc).__name__)


def wait_for_recovery(
    url: str,
    *,
    get: Callable | None = None,
    timeout: float = 60.0,
    interval: float = 2.0,
    probe_timeout: float = DEFAULT_PROBE_TIMEOUT,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[ProbeResult, float]:
    """Poll `url` until it returns 200 or `timeout` (seconds) elapses. Returns the
    last probe and the approximate seconds waited. `sleep` is injectable so unit
    tests run instantly."""
    waited = 0.0
    last = probe(url, timeout=probe_timeout, get=get)
    while not last.ok and waited < timeout:
        sleep(interval)
        waited += interval
        last = probe(url, timeout=probe_timeout, get=get)
    return last, waited


@dataclass
class ComposeController:
    """Thin wrapper over `docker compose <verb> <service>` for one compose dir.

    `runner(cmd, cwd) -> CompletedProcess` is injectable; the default shells out
    to docker. Methods return whatever the runner returns (callers rarely need
    it — the *observable* effect is asserted via probes)."""

    compose_dir: Path
    runner: Callable[[list[str], Path], object] | None = None

    def _exec(self, cmd: list[str]) -> object:
        run = self.runner or _subprocess_runner
        return run(cmd, Path(self.compose_dir))

    def _run(self, *args: str) -> object:
        return self._exec(["docker", "compose", *args])

    def pause(self, service: str = "db") -> object:
        return self._run("pause", service)

    def unpause(self, service: str = "db") -> object:
        return self._run("unpause", service)

    def kill(self, service: str = "web") -> object:
        """Operator-initiated container kill. NOTE: Docker flags this a manual
        stop, so the restart policy will NOT fire — use `crash()` to test process
        recovery. Kept as a primitive for completeness / operator-action faults."""
        return self._run("kill", service)

    def crash(self, service: str = "web", signal: str = "TERM") -> object:
        """Kill the container's main process FROM INSIDE so the daemon sees a
        *spontaneous* exit and the restart policy fires. `docker kill`/`compose
        kill` are operator stops the policy ignores, and a PID-namespace's PID 1
        can't receive SIGKILL from within — so we send a signal the app handles
        fatally (default SIGTERM → gunicorn shutdown) via the shell builtin."""
        return self._run("exec", "-T", service, "sh", "-c", f"kill -{signal} 1")

    def up(self, service: str = "web") -> object:
        return self._run("up", "-d", service)

    def restart_count(self, service: str = "web") -> int | None:
        """The container's `RestartCount` — how many times Docker's restart policy
        has restarted it. Comparing before/after proves recovery was the *policy*,
        not a coincidence. Returns None if the container can't be resolved."""
        ps = self._run("ps", "-q", service)
        cid = (getattr(ps, "stdout", "") or "").strip()
        if not cid:
            return None
        info = self._exec(["docker", "inspect", "--format", "{{.RestartCount}}", cid])
        raw = (getattr(info, "stdout", "") or "").strip()
        try:
            return int(raw)
        except ValueError:
            return None


def _subprocess_runner(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
