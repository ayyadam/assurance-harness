"""CLI for the resilience / chaos evaluation of the golf-web-app stack (B4).

Local, on-demand — like the LLM eval, it never runs in hosted CI (it pauses and
SIGKILLs containers in a live compose stack). The fast *logic* of the scenarios
is covered by gated unit tests in tests/test_chaos_scenarios.py.

    # bring the SUT up first (sibling repo), then:
    uv run python -m chaos.run                       # both v1 scenarios
    uv run python -m chaos.run --scenario db-outage  # one scenario
    uv run python -m chaos.run --compose-dir ../golf-web-app

Writes a markdown + JSON evidence artifact to chaos/reports/. The report carries
not just results but the *scope rationale* — what each axis proves, and what is
deliberately excluded — so the discipline of the testing is itself evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .faults import ComposeController, wait_for_recovery
from .latency import Prometheus, Toxiproxy, latency_compose_cmd
from .scenarios import V1_SCENARIOS, ScenarioResult, scenario_db_latency

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
DEFAULT_BASE_URL = "http://localhost:5000"
# The SUT is a sibling checkout of the harness by default (Repos/golf-web-app).
DEFAULT_COMPOSE_DIR = Path(__file__).resolve().parents[2] / "golf-web-app"
LATENCY_OVERRIDE = Path(__file__).resolve().parent / "compose.latency.yml"

# What we deliberately DON'T fault-inject, and why — scope discipline made
# visible. One representative per real failure axis; everything below is either
# already covered, has no definable correct behaviour, or is out of scope.
EXCLUSIONS = [
    (
        "Ollama / AI dependency down",
        "Already covered by design: the booking assistant degrades to a deterministic stub. That "
        "fallback *is* the resilience pattern, so it is asserted elsewhere, not re-broken here.",
    ),
    (
        "Resource exhaustion (CPU / memory / disk)",
        "The SUT has no defined behaviour under resource pressure to assert against — injecting it "
        "would be vandalism, not a test with a pass/fail.",
    ),
    (
        "Observability stack down (Prometheus / Grafana)",
        "Non-critical-path: losing dashboards does not affect user-facing correctness, so it has no "
        "graceful-degradation contract to test.",
    ),
    (
        "Multi-fault / combinatorial chaos",
        "Non-reproducible and a maturity level beyond a portfolio demo; v1 injects one fault at a "
        "time with a bounded blast radius.",
    ),
    (
        "Latency permutations (1s / 2s / 5s / …)",
        "Combinatorial padding. The grey-failure *axis* is covered once (v2, toxiproxy) with a value "
        "chosen to breach the SLO; more values add runtime, not information.",
    ),
]


def run_all(base_url: str, controller: ComposeController, only: str | None = None) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for key, fn in V1_SCENARIOS.items():
        if only and key != only:
            continue
        print(f"[chaos] running scenario '{key}' ...")
        result = fn(base_url, controller)
        held = sum(s.ok for s in result.steps)
        print(f"[chaos]   -> {result.status.upper()} ({held}/{len(result.steps)} steps held)")
        results.append(result)
    return results


# ── v2 — latency axis (manages its own compose lifecycle) ─────────────────────


def _sh(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print(f"[chaos]   $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def run_latency(
    base_url: str,
    sut_dir: Path,
    *,
    latency_ms: int = 600,
    slo_seconds: float = 0.5,
) -> ScenarioResult | None:
    """Bring the stack up in the latency topology (web → toxiproxy → db), run the
    grey-failure scenario, then ALWAYS restore the normal stack. Local-only and
    invasive (it recreates `web`), so it is opt-in via `--latency`."""
    sut_compose = sut_dir / "docker-compose.yml"
    course = f"{base_url}/course"
    print("[chaos] bringing up latency topology (web -> toxiproxy -> db) ...")
    _sh(latency_compose_cmd(sut_compose, LATENCY_OVERRIDE, "up", "-d", "--build"))
    try:
        toxi = Toxiproxy()
        # toxiproxy's API comes up fast; web crash-loops on DATABASE_URL until the
        # proxy exists, so create it (with retry) then wait for /course to heal.
        last_err: Exception | None = None
        for _ in range(20):
            try:
                toxi.ensure_proxy()
                break
            except Exception as exc:  # noqa: BLE001 - API not ready yet
                last_err = exc
                time.sleep(2)
        else:
            print(f"[chaos] toxiproxy admin API never became ready: {last_err}")
            return None

        # the proxy now exists — restart web so it re-attempts the DB connection
        # cleanly (rather than relying on crash-loop timing) and wait for /course.
        _sh(latency_compose_cmd(sut_compose, LATENCY_OVERRIDE, "restart", "web"), check=False)
        rec, waited = wait_for_recovery(course, timeout=120.0, interval=3.0)
        if not rec.ok:
            print(f"[chaos] latency topology did not become ready ({rec.describe()} after ~{waited:.0f}s); skipping")
            return None

        print("[chaos] running scenario 'db-latency' ...")
        result = scenario_db_latency(base_url, toxi, Prometheus(), latency_ms=latency_ms, slo_seconds=slo_seconds)
        held = sum(s.ok for s in result.steps)
        print(f"[chaos]   -> {result.status.upper()} ({held}/{len(result.steps)} steps held)")
        return result
    finally:
        print("[chaos] restoring the normal stack ...")
        _sh(latency_compose_cmd(sut_compose, LATENCY_OVERRIDE, "stop", "toxiproxy"), check=False)
        _sh(latency_compose_cmd(sut_compose, LATENCY_OVERRIDE, "rm", "-f", "toxiproxy"), check=False)
        _sh(["docker", "compose", "up", "-d"], cwd=sut_dir, check=False)


# ── reporting ────────────────────────────────────────────────────────────────

_STATUS_BADGE = {"passed": "✅ passed", "failed": "❌ failed", "inconclusive": "⚠️ inconclusive"}


def render_markdown(meta: dict, results: list[ScenarioResult]) -> str:
    L: list[str] = []
    L.append("# Resilience / chaos evaluation — golf-web-app")
    L.append("")
    L.append(f"- **Run:** {meta['run_at']}")
    L.append(f"- **SUT:** {meta['base_url']} (compose stack at `{meta['compose_dir']}`)")
    L.append(
        "- **Method:** steady-state hypothesis → inject one fault → assert bounded degradation + "
        "automatic recovery. One representative fault per failure *axis*."
    )
    L.append(
        "- **CI posture:** local-only (mutates a live stack); scenario *logic* is gate-tested in "
        "`tests/test_chaos_scenarios.py`."
    )
    L.append(
        "- **Fault-model note:** process death is injected *inside* the container (signalling the "
        "app's PID 1), not via `docker kill` — Docker treats an operator kill as a manual stop that "
        "the restart policy ignores, so killing the container would report a false 'no recovery'."
    )
    L.append("")

    passed = sum(r.passed for r in results)
    L.append("## Summary")
    L.append("")
    L.append(f"**{passed}/{len(results)} scenarios passed.**")
    L.append("")
    L.append("| Scenario | Failure axis | Result |")
    L.append("|---|---|---|")
    for r in results:
        L.append(f"| {r.name} | {r.axis} | {_STATUS_BADGE.get(r.status, r.status)} |")
    L.append("")

    for r in results:
        L.append(f"## {r.name} — {_STATUS_BADGE.get(r.status, r.status)}")
        L.append("")
        L.append(f"_Hypothesis:_ {r.hypothesis}")
        L.append("")
        if r.steps:
            L.append("| Step | Expected | Observed | Held |")
            L.append("|---|---|---|---|")
            for s in r.steps:
                L.append(f"| {s.name} | {s.expectation} | {s.observed} | {'✅' if s.ok else '❌'} |")
            L.append("")
        if r.notes:
            L.append(f"> {r.notes}")
            L.append("")

    L.append("## Excluded by design (scope discipline)")
    L.append("")
    L.append(
        "Chaos testing balloons into a fault-injection framework unless bounded. This layer tests "
        "*one representative per real failure axis*; the following are deliberately out of scope:"
    )
    L.append("")
    L.append("| Not tested | Why |")
    L.append("|---|---|")
    for what, why in EXCLUSIONS:
        L.append(f"| {what} | {why} |")
    L.append("")
    L.append("## Roadmap")
    L.append("")
    L.append(
        "- **v2 — grey-failure axis (shipped):** Postgres latency injected via "
        "[toxiproxy](https://github.com/Shopify/toxiproxy) between `web` and `db` — asserts graceful "
        "degradation under slowness **and** that the p95 latency SLO breaches in Prometheus (the "
        "observability stack catching a slow dependency, not just an outage). Run with `--latency`."
    )
    L.append(
        "- **Possible v3:** alerting-side assertion (Alertmanager fires on the SLO breach) once a real "
        "alert sink exists — pairs with the deferred Loki/Alertmanager observability work."
    )
    L.append("")
    return "\n".join(L)


def write_reports(meta: dict, results: list[ScenarioResult]) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORTS_DIR / "report.md"
    json_path = REPORTS_DIR / "report.json"
    md_path.write_text(render_markdown(meta, results), encoding="utf-8")
    payload = {"meta": meta, "scenarios": [asdict(r) for r in results]}
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return md_path, json_path


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resilience / chaos eval for golf-web-app.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--compose-dir",
        default=os.getenv("CHAOS_COMPOSE_DIR", str(DEFAULT_COMPOSE_DIR)),
        help="directory containing the SUT's docker-compose.yml",
    )
    parser.add_argument("--scenario", choices=sorted(V1_SCENARIOS), default=None, help="run only this v1 scenario")
    parser.add_argument(
        "--latency",
        action="store_true",
        help="also run the v2 grey-failure axis (toxiproxy latency) — INVASIVE: recreates the stack, then restores it",
    )
    parser.add_argument("--latency-ms", type=int, default=600, help="latency toxic magnitude (ms)")
    parser.add_argument("--slo", type=float, default=0.5, help="p95 latency SLO in seconds")
    args = parser.parse_args(argv)

    compose_dir = Path(args.compose_dir)
    if not (compose_dir / "docker-compose.yml").exists():
        raise SystemExit(f"no docker-compose.yml under {compose_dir} — pass --compose-dir or set CHAOS_COMPOSE_DIR")

    controller = ComposeController(compose_dir)
    results = run_all(args.base_url, controller, only=args.scenario)

    if args.latency and not args.scenario:
        lat = run_latency(args.base_url, compose_dir, latency_ms=args.latency_ms, slo_seconds=args.slo)
        if lat is not None:
            results.append(lat)

    meta = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": args.base_url,
        "compose_dir": str(compose_dir),
        "scenarios": len(results),
    }
    md_path, json_path = write_reports(meta, results)
    passed = sum(r.passed for r in results)
    print(f"[chaos] {passed}/{len(results)} scenarios passed")
    print(f"[chaos] wrote {md_path}")
    print(f"[chaos] wrote {json_path}")
    # A failed scenario is a real finding, not a harness error — exit non-zero so a
    # local runner/CI notices, but the report is always written first.
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
