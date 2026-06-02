"""LLM-planned tours, Playwright-executed steps, captured per-step state.

The flow per tour:

  1. Planner LLM call — system prompt + tour goal + starting URL + seed creds →
     a JSON plan: a list of steps with action / target / value / rationale.
  2. Deterministic executor — runs each step in Playwright, capturing URL,
     page title, simplified interactive elements list, JS console errors,
     network 5xx responses, and a screenshot per step.
  3. (Judgement lives in ``ui_judge.py`` — kept separate so the executor stays
     dumb and the judge stays focused.)

The planner is shown the page state of the **starting URL** at planning time
so its plan can refer to elements that actually exist. Re-planning during a
tour is not done in v1 — if the plan diverges from reality, the executor
records the failed steps and the judge classifies them.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ollama
from playwright.sync_api import Page

from explore_agent.tours import TourGoal

DEFAULT_MODEL = "qwen2.5:32b-instruct-q4_K_M"
ACTIONS = ("navigate", "click", "fill", "wait", "observe")


@dataclass
class Step:
    action: str  # one of ACTIONS
    target: str | None  # CSS selector, URL (for navigate), or None (for observe)
    value: str | None  # text to fill (for fill), or None
    rationale: str  # one-line description of why this step


@dataclass
class StepResult:
    step: Step
    started_at: datetime
    succeeded: bool  # action completed without raising
    error_message: str | None
    page_url: str
    page_title: str
    interactive_elements: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    network_5xx: list[str] = field(default_factory=list)
    screenshot_path: str | None = None
    elapsed_ms: float = 0.0


# ── page state extraction ─────────────────────────────────────────────────


_INTERACTIVE_JS = """
() => {
    const out = [];
    document.querySelectorAll('a, button, input, textarea, select').forEach(el => {
        const tag = el.tagName.toLowerCase();
        const id = el.id ? '#' + el.id : '';
        const role = el.getAttribute('role') || '';
        let label = '';
        if (tag === 'a') {
            label = (el.textContent || '').trim().slice(0, 60);
        } else if (tag === 'button') {
            label = (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 60);
        } else if (tag === 'input' || tag === 'textarea') {
            label = el.getAttribute('placeholder')
                || el.getAttribute('name')
                || el.getAttribute('type')
                || '';
        } else if (tag === 'select') {
            label = el.getAttribute('name') || '';
        }
        const href = el.getAttribute('href') || '';
        out.push({tag, id, role, label, href});
    });
    return out;
}
"""


def _snapshot_interactive(page: Page) -> list[str]:
    """Return a compact ``tag#id "label"`` list of interactive elements."""
    try:
        items = page.evaluate(_INTERACTIVE_JS)
    except Exception:
        return []
    rows: list[str] = []
    for el in items[:80]:  # cap to keep LLM context tight
        tag = el.get("tag", "")
        sid = el.get("id", "")
        label = (el.get("label") or "").replace("\n", " ").strip()
        href = el.get("href", "")
        href_suffix = f" -> {href}" if href and tag == "a" else ""
        rows.append(f'{tag}{sid} "{label}"{href_suffix}'.strip())
    return rows


# ── LLM planner ───────────────────────────────────────────────────────────


_PLANNER_SYSTEM = (
    "You are an exploratory testing agent driving a real web browser via Playwright. "
    "Given a tour goal and the current page state (URL, title, interactive elements), "
    "plan a sequence of browser steps to achieve the goal.\n\n"
    "Each step is ONE action from this enum:\n"
    "  navigate — go to a URL (target = relative path like '/auth/login' or absolute URL)\n"
    "  click    — click an element (target = a CSS selector, prefer an id like '#sign-in-button')\n"
    "  fill     — type into an input (target = CSS selector, value = text to type)\n"
    "  wait     — wait briefly (target = a CSS selector to wait for, or null)\n"
    "  observe  — no-op, capture current state (used as a terminal step)\n\n"
    "Rules:\n"
    "  - Use CSS selectors only. Prefer id selectors (#foo) when available — they were "
    "    listed in the interactive-elements list with a leading '#'.\n"
    "  - For navigate, target may be a relative path or absolute URL.\n"
    "  - Do NOT exceed the supplied step budget. Plan exactly N steps where N ≤ budget.\n"
    "  - The final step MUST verify the goal was reached (observe is fine).\n"
    "  - Each step needs a one-sentence rationale grounded in the goal.\n"
    "  - If the goal requires being logged in and the page state does not show member "
    "    nav, START the plan with login form steps using the supplied credentials."
)


_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": list(ACTIONS)},
                    "target": {"type": ["string", "null"]},
                    "value": {"type": ["string", "null"]},
                    "rationale": {"type": "string"},
                },
                "required": ["action", "target", "value", "rationale"],
            },
        }
    },
    "required": ["steps"],
}


def _planner_user_message(
    tour: TourGoal,
    base_url: str,
    page_url: str,
    page_title: str,
    interactive: list[str],
    creds: tuple[str, str] | None,
) -> str:
    creds_blob = (
        f"Seed credentials available: username={creds[0]!r}, password={creds[1]!r}.\n"
        if creds
        else "No credentials needed for this tour.\n"
    )
    elements_blob = "\n".join(f"  - {e}" for e in interactive) or "  (no interactive elements detected)"
    return (
        f"Tour: {tour.name}\n"
        f"Goal: {tour.description}\n"
        f"Step budget: at most {tour.max_steps} steps.\n\n"
        f"Base URL: {base_url}\n"
        f"Current page URL: {page_url}\n"
        f"Current page title: {page_title!r}\n"
        f"{creds_blob}\n"
        f'Interactive elements visible on this page (tag#id "label" -> href):\n'
        f"{elements_blob}\n\n"
        "Plan the tour. Return the steps array."
    )


def plan_tour(
    tour: TourGoal,
    base_url: str,
    page: Page,
    creds: tuple[str, str] | None,
    model: str = DEFAULT_MODEL,
    host: str | None = None,
) -> list[Step]:
    """Snapshot the current page, ask the LLM for a step-by-step plan."""
    page_url = page.url
    page_title = page.title()
    interactive = _snapshot_interactive(page)
    client = ollama.Client(host=host) if host else ollama
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _PLANNER_SYSTEM},
            {
                "role": "user",
                "content": _planner_user_message(tour, base_url, page_url, page_title, interactive, creds),
            },
        ],
        "format": _PLAN_SCHEMA,
        "options": {"temperature": 0},
    }
    try:
        response = client.chat(think=False, **kwargs)
    except ollama.ResponseError:
        response = client.chat(**kwargs)
    parsed = json.loads(response["message"]["content"])
    return [
        Step(
            action=s["action"],
            target=s.get("target"),
            value=s.get("value"),
            rationale=s["rationale"],
        )
        for s in parsed["steps"][: tour.max_steps]
    ]


# ── Playwright executor ───────────────────────────────────────────────────


def attach_listeners(page: Page, console_errors: list[str], network_5xx: list[str]) -> None:
    """Wire up error capture on a fresh page. Call once per page."""
    page.on("console", lambda msg: console_errors.append(f"{msg.type}: {msg.text}") if msg.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
    page.on(
        "response",
        lambda r: network_5xx.append(f"{r.status} {r.url}") if r.status >= 500 else None,
    )


def _execute_step(
    page: Page,
    step: Step,
    base_url: str,
) -> tuple[bool, str | None]:
    """Dispatch on action type. Return (succeeded, error_message)."""
    try:
        if step.action == "navigate":
            target = step.target or "/"
            if target.startswith("http"):
                url = target
            else:
                suffix = target if target.startswith("/") else "/" + target
                url = base_url.rstrip("/") + suffix
            page.goto(url, wait_until="domcontentloaded", timeout=15_000)
        elif step.action == "click":
            if not step.target:
                return False, "click step has no target"
            page.click(step.target, timeout=10_000)
        elif step.action == "fill":
            if not step.target:
                return False, "fill step has no target"
            page.fill(step.target, step.value or "", timeout=10_000)
        elif step.action == "wait":
            if step.target:
                page.wait_for_selector(step.target, timeout=10_000)
            else:
                page.wait_for_timeout(500)
        elif step.action == "observe":
            page.wait_for_timeout(200)  # let any in-flight rendering settle
        else:
            return False, f"unknown action {step.action!r}"
    except Exception as exc:
        return False, str(exc)[:300]
    return True, None


def execute_plan(
    page: Page,
    plan: list[Step],
    base_url: str,
    screenshot_dir: Path,
    tour_name: str,
    console_errors: list[str],
    network_5xx: list[str],
) -> list[StepResult]:
    """Run each step, capturing post-step state and screenshot."""
    results: list[StepResult] = []
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    for i, step in enumerate(plan, start=1):
        # Snapshot pre-step error counts so we can attribute new errors to this step.
        pre_console = len(console_errors)
        pre_net = len(network_5xx)
        started = time.perf_counter()
        started_at = datetime.now(UTC)
        ok, err = _execute_step(page, step, base_url)
        elapsed = (time.perf_counter() - started) * 1000
        # Snapshot post-step page state.
        try:
            page_url = page.url
            page_title = page.title()
        except Exception:
            page_url = "(unavailable)"
            page_title = "(unavailable)"
        interactive = _snapshot_interactive(page) if ok else []
        screenshot_path = screenshot_dir / f"{tour_name}-step-{i:02d}.png"
        try:
            page.screenshot(path=str(screenshot_path), full_page=False, timeout=5_000)
        except Exception:
            screenshot_path = None  # type: ignore[assignment]
        results.append(
            StepResult(
                step=step,
                started_at=started_at,
                succeeded=ok,
                error_message=err,
                page_url=page_url,
                page_title=page_title,
                interactive_elements=interactive,
                console_errors=console_errors[pre_console:],
                network_5xx=network_5xx[pre_net:],
                screenshot_path=str(screenshot_path) if screenshot_path else None,
                elapsed_ms=elapsed,
            )
        )
    return results
