"""Classify each UI step outcome into a finding category, with rationale.

Closed enum, intentionally narrow. The judge looks at:
  - what the step intended (action + target + rationale)
  - what happened (succeeded? error? page state? console errors? 5xx?)
  - the tour goal
and assigns one of five categories.

The judgement is per-step. A tour can have a mix — early steps may be
``expected`` while a late step is ``dead_end``. The report orders steps by
sequence (not by severity) so a reader can follow the tour as it unfolded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import ollama

from explore_agent.tours import TourGoal
from explore_agent.ui_probe import StepResult

DEFAULT_MODEL = "qwen2.5:32b-instruct-q4_K_M"

CATEGORIES = ("expected", "unexpected_5xx", "js_error", "dead_end", "business_rule_concern")
SEVERITIES = ("low", "med", "high")


@dataclass
class StepFinding:
    category: str
    severity: str  # placeholder when category == "expected"
    rationale: str


_SYSTEM = (
    "You are reviewing one step of an exploratory UI test against a web application. "
    "You see what the step intended, what happened, and the tour goal it was advancing. "
    "Classify the step into exactly ONE category and give a one-to-two-sentence rationale "
    "grounded in specific evidence (the error message, a console error, the page URL, the "
    "tour goal alignment).\n\n"
    "Judge THIS STEP, not whether the whole tour goal is complete yet. A tour reaches its "
    "goal over several steps; an intermediate step that does its own small job is a success "
    "even when the final goal is not yet met. The executor's `succeeded` flag is the source "
    "of truth for whether the action actually executed — trust it over any inference you "
    "draw from the page (an unchanged URL is NOT evidence of failure).\n\n"
    "Choose the category in this order:\n"
    "  1. A network 5xx was captured → unexpected_5xx.\n"
    "  2. Else a JavaScript console/page error broke behaviour → js_error.\n"
    "  3. Else succeeded=false — the action did NOT execute (selector not found, wait timed "
    "out, exception) → dead_end.\n"
    "  4. Else succeeded=true — the action executed, so it is NOT a dead_end: if the "
    "resulting state is technically valid but suspect → business_rule_concern; otherwise → "
    "expected.\n\n"
    "Categories:\n"
    "  expected               — The step executed without error (succeeded=true) and is a "
    "                           legitimate move toward the goal. This INCLUDES intermediate "
    "                           steps that correctly stay on the same page: a fill, wait, or "
    "                           observe that succeeds but does not change the URL is "
    "                           'expected' — filling a field does not navigate, so an "
    "                           unchanged URL after a successful fill is the correct state, "
    "                           not a failure. A successful navigation or form submission "
    "                           that lands on the expected page is also 'expected'.\n"
    "  unexpected_5xx         — A network 5xx was captured during the step, or the page "
    "                           clearly shows a server-error indicator.\n"
    "  js_error               — A JavaScript console error or page error was captured that "
    "                           affects behaviour (e.g. a click handler threw). Trivial 404s "
    "                           on optional assets are NOT a js_error.\n"
    "  dead_end               — The step's intended action DID NOT EXECUTE: the executor "
    "                           reported succeeded=false (selector not found, wait timed "
    "                           out, exception raised), so the tour cannot progress. The "
    "                           succeeded flag is authoritative — if succeeded=true the "
    "                           action ran, and the step is NOT a dead_end regardless of "
    "                           whether the URL changed. Do NOT infer 'stuck' from an "
    "                           unchanged URL after a SUCCESSFUL step.\n"
    "  business_rule_concern  — The step executed cleanly but the resulting page state "
    "                           suggests a business-rule weakness — e.g. a member dashboard "
    "                           that exposes data the member should not see, a form that "
    "                           accepts an invalid value silently.\n\n"
    "Severity: low | med | high. Use 'low' for 'expected'.\n"
    "Do NOT speculate about exploits — categorise, ground the rationale, stop."
)


_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "rationale": {"type": "string"},
    },
    "required": ["category", "severity", "rationale"],
}


def _user_message(tour: TourGoal, result: StepResult) -> str:
    elements_blob = "\n".join(f"  - {e}" for e in result.interactive_elements[:30]) or "  (none)"
    return (
        f"Tour goal: {tour.description}\n\n"
        f"Step intent:\n"
        f"  action:    {result.step.action}\n"
        f"  target:    {result.step.target!r}\n"
        f"  value:     {result.step.value!r}\n"
        f"  rationale: {result.step.rationale}\n\n"
        f"What happened:\n"
        f"  succeeded:      {result.succeeded}\n"
        f"  error message:  {result.error_message!r}\n"
        f"  page URL after: {result.page_url}\n"
        f"  page title:     {result.page_title!r}\n"
        f"  elapsed ms:     {result.elapsed_ms:.0f}\n"
        f"  console errors: {result.console_errors or '(none)'}\n"
        f"  network 5xx:    {result.network_5xx or '(none)'}\n"
        f"  interactive elements now visible:\n{elements_blob}\n\n"
        "Classify."
    )


def judge_step(
    tour: TourGoal,
    result: StepResult,
    model: str = DEFAULT_MODEL,
    host: str | None = None,
) -> StepFinding:
    client = ollama.Client(host=host) if host else ollama
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _user_message(tour, result)},
        ],
        "format": _SCHEMA,
        "options": {"temperature": 0},
    }
    try:
        response = client.chat(think=False, **kwargs)
    except ollama.ResponseError:
        response = client.chat(**kwargs)
    parsed = json.loads(response["message"]["content"])
    return StepFinding(
        category=parsed["category"],
        severity=parsed["severity"],
        rationale=parsed["rationale"],
    )
