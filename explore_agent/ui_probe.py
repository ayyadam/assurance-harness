"""Adaptive single-step UI exploration: an LLM *policy*, Playwright-executed.

This is the policy-based successor to the plan-based UI agent (phase 12 v1 v2,
preserved in git history). The difference is structural:

  - The old agent **planned once** from the starting page, then executed the
    whole plan blindly. Selectors for pages it had not yet seen were invented —
    the booking-assistant tour waited for ``.candidate-slot`` (hallucinated)
    while the real class is ``.booking-slot``. A plan cannot perceive.
  - This agent runs a **perceive → decide → act loop**. Each step it snapshots
    the CURRENT page (URL, title, the interactive elements actually present),
    shows that plus the history so far to the LLM, and asks for exactly ONE next
    action. It then executes that one action, re-perceives, and asks again.

Because the model only ever chooses selectors from the elements it has just been
shown, hallucinating a selector for an unseen page is structurally impossible —
that is the whole point of a policy over a plan.

The loop stops when the LLM emits ``finish`` (goal reached, or stuck — with a
reason) or when the tour's ``max_steps`` budget is exhausted. Judgement still
lives in ``ui_judge.py`` (per-step), kept separate so the executor stays dumb
and the judge stays focused.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ollama
from playwright.sync_api import Page

from explore_agent.tours import TourGoal

DEFAULT_MODEL = "qwen2.5:32b-instruct-q4_K_M"
# ``finish`` is a control signal, not a browser action — the loop breaks on it
# and it is never dispatched to the executor.
ACTIONS = ("navigate", "click", "fill", "wait", "observe", "finish")


@dataclass
class Step:
    action: str  # one of ACTIONS
    target: str | None  # CSS selector, URL (for navigate), or None
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


@dataclass
class PageState:
    """What the policy is shown about the current page before each decision."""

    url: str
    title: str
    interactive: list[str] = field(default_factory=list)


@dataclass
class TourRun:
    """Outcome of one adaptive tour: the steps taken plus how it terminated."""

    steps: list[StepResult]
    finish_reason: str | None  # the LLM's stated reason if it chose to finish; None if the cap was hit
    hit_cap: bool  # True if the loop exhausted max_steps without the agent finishing


# ── page state extraction ─────────────────────────────────────────────────


# Perceive standard form controls AND non-standard clickables. The booking
# assistant renders its result slots as ``<div class="booking-slot" onclick=…>``
# cards, not buttons — without ``[onclick]`` / interactive ``[role]`` here the
# agent cannot see that results arrived (F-028). A comma selector returns each
# element at most once, so no dedup is needed.
_INTERACTIVE_JS = """
() => {
    const out = [];
    const selector = 'a, button, input, textarea, select, '
        + '[onclick], [role="button"], [role="link"], [role="option"], [role="menuitem"]';
    document.querySelectorAll(selector).forEach(el => {
        const tag = el.tagName.toLowerCase();
        const id = el.id ? '#' + el.id : '';
        // Fall back to the first class when there is no id, so non-standard
        // clickables (e.g. div.booking-slot) get a usable selector hint.
        const cls = (!el.id && el.classList.length) ? '.' + el.classList[0] : '';
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
        } else {
            // non-standard clickable (div/span/li with onclick or an interactive role)
            label = (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 60);
        }
        const href = el.getAttribute('href') || '';
        out.push({tag, id, cls, role, label, href});
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
        sid = el.get("id", "") or el.get("cls", "")  # prefer #id, else .firstclass
        label = (el.get("label") or "").replace("\n", " ").strip()
        href = el.get("href", "")
        href_suffix = f" -> {href}" if href and tag == "a" else ""
        rows.append(f'{tag}{sid} "{label}"{href_suffix}'.strip())
    return rows


def _snapshot_state(page: Page) -> PageState:
    """Capture the current page as the policy sees it (url, title, elements)."""
    try:
        url = page.url
        title = page.title()
    except Exception:
        url, title = "(unavailable)", "(unavailable)"
    return PageState(url=url, title=title, interactive=_snapshot_interactive(page))


# ── LLM policy ────────────────────────────────────────────────────────────


_POLICY_SYSTEM = (
    "You are an exploratory testing agent driving a real web browser via Playwright, "
    "ONE action at a time. This is a perceive-decide-act loop, not an upfront plan: each "
    "turn you are shown the CURRENT page (its URL, title, and the interactive elements "
    "ACTUALLY present on it) plus the history of what you have done, and you choose exactly "
    "ONE next action to advance the tour goal. You will then be shown the result and asked "
    "again.\n\n"
    "Each action is ONE of:\n"
    "  navigate — go to a URL (target = relative path like '/auth/login', or absolute URL)\n"
    "  click    — click an element (target = a CSS selector)\n"
    "  fill     — type into an input (target = CSS selector, value = text to type)\n"
    "  wait     — wait for a selector to appear (target = CSS selector), or briefly (target = null)\n"
    "  observe  — re-capture the current page without acting (rarely needed; you re-perceive every turn)\n"
    "  finish   — stop the tour. Set rationale to WHY: goal reached, or you cannot progress.\n\n"
    "Selector discipline (this is the point of the loop):\n"
    "  - Every CSS selector you use MUST be one of the interactive elements listed for the "
    "CURRENT page. Prefer id selectors (#foo); they are shown with a leading '#'.\n"
    "  - NEVER invent a selector for an element you have not been shown. If what you need is "
    "not in the list, either it has not rendered yet (use wait), or you are on the wrong page "
    "(navigate), or the goal cannot be met from here (finish).\n"
    "  - If your previous action FAILED with 'selector not found', do NOT retry the same "
    "selector — pick a real one from the current list, or finish.\n\n"
    "Progress discipline:\n"
    "  - Advance the goal each turn; do not repeat an action that already succeeded.\n"
    "  - Emit finish the moment the goal is reached, or as soon as you are stuck. Do not burn "
    "the remaining budget once there is nothing left to learn.\n"
    "  - Honour scope limits stated in the goal (e.g. 'stop at suggestions; do not confirm').\n"
    "  - If the goal needs you logged in and the current page is a login form, fill username "
    "and password from the supplied credentials and submit.\n"
    "  - Give a one-sentence rationale, grounded in the goal and what is on the current page."
)


_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "target": {"type": ["string", "null"]},
        "value": {"type": ["string", "null"]},
        "rationale": {"type": "string"},
    },
    "required": ["action", "target", "value", "rationale"],
}


def _render_history(history: list[StepResult]) -> str:
    """Compact trail of prior actions + outcomes — NOT the full element dumps."""
    if not history:
        return "  (nothing yet — this is your first action)"
    lines: list[str] = []
    for i, r in enumerate(history, start=1):
        s = r.step
        bit = f"  {i}. {s.action}"
        if s.target:
            bit += f" {s.target}"
        if s.value:
            bit += f" = {s.value!r}"
        if r.succeeded:
            bit += f"  → OK, now at {r.page_url}"
        else:
            bit += f"  → FAILED: {r.error_message}"
        lines.append(bit)
    return "\n".join(lines)


def _policy_user_message(
    tour: TourGoal,
    base_url: str,
    state: PageState,
    history: list[StepResult],
    creds: tuple[str, str] | None,
) -> str:
    creds_blob = (
        f"Seed credentials available: username={creds[0]!r}, password={creds[1]!r}.\n"
        if creds
        else "No credentials needed for this tour.\n"
    )
    elements_blob = "\n".join(f"  - {e}" for e in state.interactive) or "  (no interactive elements detected)"
    return (
        f"Tour: {tour.name}\n"
        f"Goal: {tour.description}\n"
        f"Budget: at most {tour.max_steps} actions; this is action {len(history) + 1}.\n\n"
        f"Base URL: {base_url}\n"
        f"{creds_blob}\n"
        f"History so far:\n{_render_history(history)}\n\n"
        f"CURRENT page URL: {state.url}\n"
        f"CURRENT page title: {state.title!r}\n"
        f'Interactive elements on THIS page (tag#id "label" -> href):\n{elements_blob}\n\n'
        "Choose the single next action to advance the goal."
    )


def decide_next_action(
    tour: TourGoal,
    base_url: str,
    state: PageState,
    history: list[StepResult],
    creds: tuple[str, str] | None,
    model: str = DEFAULT_MODEL,
    host: str | None = None,
) -> Step:
    """Ask the LLM for the single next action, given the CURRENT page + history."""
    client = ollama.Client(host=host) if host else ollama
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _POLICY_SYSTEM},
            {"role": "user", "content": _policy_user_message(tour, base_url, state, history, creds)},
        ],
        "format": _DECISION_SCHEMA,
        "options": {"temperature": 0},
    }
    try:
        response = client.chat(think=False, **kwargs)
    except ollama.ResponseError:
        response = client.chat(**kwargs)
    parsed = json.loads(response["message"]["content"])
    return Step(
        action=parsed["action"],
        target=parsed.get("target"),
        value=parsed.get("value"),
        rationale=parsed["rationale"],
    )


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
    """Dispatch on action type. Return (succeeded, error_message).

    ``finish`` never reaches here — the loop breaks on it before executing.
    """
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


def _execute_and_capture(
    page: Page,
    step: Step,
    base_url: str,
    screenshot_dir: Path,
    tour_name: str,
    step_num: int,
    console_errors: list[str],
    network_5xx: list[str],
) -> StepResult:
    """Execute one step and capture the resulting page state + screenshot."""
    # Snapshot pre-step error counts so we can attribute new errors to this step.
    pre_console = len(console_errors)
    pre_net = len(network_5xx)
    started = time.perf_counter()
    started_at = datetime.now(UTC)
    ok, err = _execute_step(page, step, base_url)
    elapsed = (time.perf_counter() - started) * 1000
    try:
        page_url = page.url
        page_title = page.title()
    except Exception:
        page_url = "(unavailable)"
        page_title = "(unavailable)"
    # Always snapshot — even after a FAILED action — so the next decision sees the
    # page as it really is and can recover. (The plan-based agent blanked the element
    # list on failure; a policy must perceive to adapt.)
    interactive = _snapshot_interactive(page)
    screenshot_path: Path | None = screenshot_dir / f"{tour_name}-step-{step_num:02d}.png"
    try:
        page.screenshot(path=str(screenshot_path), full_page=False, timeout=5_000)
    except Exception:
        screenshot_path = None
    return StepResult(
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


def run_tour(
    tour: TourGoal,
    base_url: str,
    page: Page,
    creds: tuple[str, str] | None,
    screenshot_dir: Path,
    console_errors: list[str],
    network_5xx: list[str],
    model: str = DEFAULT_MODEL,
    host: str | None = None,
    log: Callable[[str], None] | None = None,
) -> TourRun:
    """Perceive → decide → act loop: one LLM decision per step from the CURRENT page.

    The page is assumed already navigated to the tour's starting URL (and pre-authed
    if the tour requires it). Each iteration snapshots the current page, asks the policy
    for ONE next action, executes it, captures the result, and feeds it back as history.
    Stops when the agent emits ``finish`` or the ``max_steps`` budget is exhausted.
    """
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    results: list[StepResult] = []
    state = _snapshot_state(page)
    finish_reason: str | None = None
    hit_cap = False
    for step_num in range(1, tour.max_steps + 1):
        decision = decide_next_action(tour, base_url, state, results, creds, model=model, host=host)
        if decision.action == "finish":
            finish_reason = decision.rationale
            if log:
                log(f"  step {step_num}: finish — {decision.rationale}")
            break
        if log:
            tgt = f" {decision.target}" if decision.target else ""
            log(f"  step {step_num}: {decision.action}{tgt}")
        result = _execute_and_capture(
            page, decision, base_url, screenshot_dir, tour.name, step_num, console_errors, network_5xx
        )
        results.append(result)
        # Re-perceive from the post-action page so the next decision sees reality.
        state = PageState(url=result.page_url, title=result.page_title, interactive=result.interactive_elements)
    else:
        # Loop ran the full budget without the agent emitting finish.
        hit_cap = True
    return TourRun(steps=results, finish_reason=finish_reason, hit_cap=hit_cap)
