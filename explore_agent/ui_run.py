"""CLI for the UI-level exploratory agent (phase 12 v1 v2).

Drives Playwright through three predefined tours (see ``tours.py``), with the
LLM planning each tour from the starting page state and the LLM judging each
step's outcome. Screenshots, console errors, and a markdown + JSON report
land under ``explore_agent/reports/ui/``.

Usage:
  uv run python -m explore_agent.ui_run
  uv run python -m explore_agent.ui_run --base-url http://localhost:5000
  uv run python -m explore_agent.ui_run --tour booking-assistant   # single tour
  uv run python -m explore_agent.ui_run --headed                   # show browser
  uv run python -m explore_agent.ui_run --no-llm                   # not supported here
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

from explore_agent.tours import TOURS, TourGoal, get_tour
from explore_agent.ui_judge import DEFAULT_MODEL, StepFinding, judge_step
from explore_agent.ui_probe import (
    StepResult,
    attach_listeners,
    execute_plan,
    plan_tour,
)

REPORTS_DIR = Path(__file__).resolve().parent / "reports" / "ui"
DEFAULT_BASE_URL = "http://localhost:5000"
DEFAULT_USERNAME = "john.smith"
DEFAULT_PASSWORD = "Password1"  # noqa: S105 — seed fixture credential


@dataclass
class TourResult:
    tour: TourGoal
    steps: list[StepResult]
    findings: list[StepFinding]


# ── pre-auth helper ───────────────────────────────────────────────────────


def _login_via_ui(page, base_url: str, username: str, password: str) -> None:
    """Drive the login form to obtain a session cookie for auth-required tours."""
    page.goto(base_url.rstrip("/") + "/auth/login", wait_until="domcontentloaded", timeout=15_000)
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#sign-in-button")
    page.wait_for_url("**/member/dashboard", timeout=15_000)


# ── markdown renderer ─────────────────────────────────────────────────────


_CATEGORY_RANK = {
    "unexpected_5xx": 0,
    "dead_end": 1,
    "js_error": 2,
    "business_rule_concern": 3,
    "expected": 4,
}


def _render_markdown(tour_results: list[TourResult], base_url: str, model: str, today: date) -> str:
    lines: list[str] = []
    lines.append("# Exploratory probe — golf-web-app UI tours")
    lines.append("")
    lines.append(f"_Run: {today.isoformat()} • base url: `{base_url}` • model: `{model}`_")
    lines.append("")

    if not tour_results:
        lines.append("_No tours ran._")
        return "\n".join(lines)

    # Summary table — one row per tour.
    lines.append("## Summary")
    lines.append("")
    lines.append("| Tour | Steps | Worst category | Failed steps |")
    lines.append("|---|---|---|---|")
    for tr in tour_results:
        worst = "expected"
        for f in tr.findings:
            if _CATEGORY_RANK[f.category] < _CATEGORY_RANK[worst]:
                worst = f.category
        failed = sum(1 for s in tr.steps if not s.succeeded)
        lines.append(f"| `{tr.tour.name}` | {len(tr.steps)} | `{worst}` | {failed} |")
    lines.append("")

    # Per-tour detail.
    for tr in tour_results:
        lines.append(f"## Tour — `{tr.tour.name}`")
        lines.append("")
        lines.append(f"**Goal:** {tr.tour.description}")
        lines.append("")
        lines.append(f"**Starting URL:** `{tr.tour.starting_url}` • **Max steps:** {tr.tour.max_steps}")
        lines.append("")
        for i, (s, f) in enumerate(zip(tr.steps, tr.findings, strict=False), start=1):
            sev = f.severity if f.category != "expected" else "—"
            status = "OK" if s.succeeded else "ERR"
            lines.append(f"### Step {i} — `{s.step.action}` ({status})")
            lines.append("")
            lines.append(f"**Category:** `{f.category}` • **Severity:** {sev}")
            lines.append("")
            lines.append(f"**Plan rationale:** {s.step.rationale}")
            lines.append("")
            lines.append(f"**Judge rationale:** {f.rationale}")
            lines.append("")
            lines.append(f"**Action:** `{s.step.action}` target=`{s.step.target}` value=`{s.step.value}`")
            lines.append("")
            lines.append(f"**After:** URL=`{s.page_url}` • title=`{s.page_title}` • elapsed `{s.elapsed_ms:.0f} ms`")
            lines.append("")
            if s.error_message:
                lines.append(f"**Error:** `{s.error_message}`")
                lines.append("")
            if s.console_errors:
                lines.append("**Console errors:**")
                for ce in s.console_errors:
                    lines.append(f"  - `{ce}`")
                lines.append("")
            if s.network_5xx:
                lines.append("**Network 5xx:**")
                for n in s.network_5xx:
                    lines.append(f"  - `{n}`")
                lines.append("")
            if s.screenshot_path:
                rel = Path(s.screenshot_path).name
                lines.append(f"![step {i} screenshot](screenshots/{rel})")
                lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by `explore_agent.ui_run` (phase 12 v1 v2). Advisory — findings are a "
        "starting point for a reviewer, not a gate. See [`explore_agent/README.md`](../../README.md)._"
    )
    lines.append("")
    return "\n".join(lines)


def _to_json(tour_results: list[TourResult]) -> str:
    out = []
    for tr in tour_results:
        out.append(
            {
                "tour": {
                    "name": tr.tour.name,
                    "description": tr.tour.description,
                    "starting_url": tr.tour.starting_url,
                    "requires_auth": tr.tour.requires_auth,
                    "max_steps": tr.tour.max_steps,
                },
                "steps": [
                    {
                        "n": i + 1,
                        "step": {
                            "action": s.step.action,
                            "target": s.step.target,
                            "value": s.step.value,
                            "rationale": s.step.rationale,
                        },
                        "result": {
                            "started_at": s.started_at.isoformat(),
                            "succeeded": s.succeeded,
                            "error_message": s.error_message,
                            "page_url": s.page_url,
                            "page_title": s.page_title,
                            "console_errors": s.console_errors,
                            "network_5xx": s.network_5xx,
                            "elapsed_ms": round(s.elapsed_ms, 2),
                            "screenshot_path": s.screenshot_path,
                        },
                        "finding": {
                            "category": f.category,
                            "severity": f.severity,
                            "rationale": f.rationale,
                        },
                    }
                    for i, (s, f) in enumerate(zip(tr.steps, tr.findings, strict=False))
                ],
            }
        )
    return json.dumps(out, indent=2)


# ── main ──────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Exploratory testing agent — UI-level.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--host", default=None, help="Ollama host (default: env or localhost)")
    parser.add_argument(
        "--tour",
        default=None,
        help="Run only one tour by name (default: all). See tours.py for names.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window. Default: headless.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print markdown to stdout but do not save report files.",
    )
    args = parser.parse_args(argv)

    tours_to_run: list[TourGoal] = [get_tour(args.tour)] if args.tour else list(TOURS)
    print(f"running {len(tours_to_run)} tour(s) via {args.model}", file=sys.stderr)

    screenshots_dir = REPORTS_DIR / "screenshots"
    tour_results: list[TourResult] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        try:
            for tour in tours_to_run:
                print(f"\n── tour: {tour.name} ──", file=sys.stderr)
                context = browser.new_context()
                page = context.new_page()
                console_errors: list[str] = []
                network_5xx: list[str] = []
                attach_listeners(page, console_errors, network_5xx)
                try:
                    if tour.requires_auth:
                        print("  pre-auth via UI login form...", file=sys.stderr)
                        _login_via_ui(page, args.base_url, args.username, args.password)
                    print(f"  navigating to {tour.starting_url}...", file=sys.stderr)
                    page.goto(
                        args.base_url.rstrip("/") + tour.starting_url,
                        wait_until="domcontentloaded",
                        timeout=15_000,
                    )
                    creds = (args.username, args.password) if tour.requires_auth or "login" in tour.name else None
                    print("  planning...", file=sys.stderr)
                    plan = plan_tour(tour, args.base_url, page, creds, model=args.model, host=args.host)
                    print(f"  plan: {len(plan)} step(s)", file=sys.stderr)
                    steps = execute_plan(
                        page,
                        plan,
                        args.base_url,
                        screenshots_dir,
                        tour.name,
                        console_errors,
                        network_5xx,
                    )
                    print("  judging...", file=sys.stderr)
                    findings = [judge_step(tour, sr, model=args.model, host=args.host) for sr in steps]
                    tour_results.append(TourResult(tour=tour, steps=steps, findings=findings))
                except Exception as exc:
                    print(f"  tour failed: {exc}", file=sys.stderr)
                finally:
                    context.close()
        finally:
            browser.close()

    md = _render_markdown(tour_results, base_url=args.base_url, model=args.model, today=date.today())
    print(md)

    if not args.no_write:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "report.md").write_text(md, encoding="utf-8")
        (REPORTS_DIR / "report.json").write_text(_to_json(tour_results), encoding="utf-8")
        print(f"\nWrote: {REPORTS_DIR / 'report.md'}", file=sys.stderr)
        print(f"       {REPORTS_DIR / 'report.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
