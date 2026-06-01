"""LLM-judge tier for the AI evaluation harness.

Two judge calls per case:
  * holistic — rate the system's interpretation of the input on a 0–10 scale.
  * fuzzy    — for cases where the correct answer is a *range* (e.g. "sometime
               this weekend" admits Saturday or Sunday), judge pass/fail against
               a per-case rubric instead of exact field equality.

The judge model runs in Ollama, separately from the model under test, so the
same harness call works regardless of which model the SUT is currently running.
Calls use structured output (a JSON schema) so the responses parse reliably.
"""

from __future__ import annotations

import json
from typing import Any

import ollama

DEFAULT_JUDGE_MODEL = "qwen2.5:32b-instruct-q4_K_M"

_HOLISTIC_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 10},
        "rationale": {"type": "string"},
    },
    "required": ["score", "rationale"],
}

_FUZZY_SCHEMA = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "rationale": {"type": "string"},
    },
    "required": ["passed", "rationale"],
}

_HOLISTIC_SYSTEM = (
    "You evaluate a golf-club booking assistant. The assistant takes a member's free-text "
    "request and extracts a structured BookingIntent with these fields:\n"
    "  date         (YYYY-MM-DD)\n"
    "  period       morning | afternoon | any\n"
    "  group_size   1..4 (the member counts as one player)\n"
    "  players      named playing partners (a count like 'two mates' is NOT a name)\n"
    "  not_before   earliest acceptable tee time HH:MM, or null\n"
    "  not_after    latest acceptable tee time HH:MM, or null\n"
    "Score how reasonable the interpretation is on a 0..10 scale: 10 = correct on every "
    "field; 7-9 = small flaw (one field off or a stylistic choice); 4-6 = a real "
    "misunderstanding; 0-3 = mostly wrong. period and time-window are orthogonal: a member "
    "stating only a clock time ('from 9am') leaves period as 'any'; inferring period from a "
    "time bound silently over-constrains the matcher and is a real flaw."
)

_FUZZY_SYSTEM = (
    "You evaluate a golf-club booking assistant. The assistant takes a member's free-text "
    "request and extracts a structured BookingIntent. You are given a rubric describing "
    "what an acceptable interpretation looks like for this case (the rubric may allow a "
    "range of correct answers). Decide whether the assistant's response satisfies the rubric."
)


def _call(model: str, system: str, user: str, schema: dict, host: str | None) -> dict:
    """Call the judge model with structured output. Falls back if think=False is rejected."""
    client = ollama.Client(host=host) if host else ollama
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": schema,
        "options": {"temperature": 0},
    }
    try:
        response = client.chat(think=False, **kwargs)
    except ollama.ResponseError:
        response = client.chat(**kwargs)
    return json.loads(response["message"]["content"])


def judge_holistic(
    input_text: str, intent: dict | None, model: str = DEFAULT_JUDGE_MODEL, host: str | None = None
) -> dict:
    """Rate the interpretation 0..10. Returns {score, rationale}."""
    user = f"Member's request: {input_text!r}\nAssistant's interpretation: {intent!r}\n\nScore it."
    return _call(model, _HOLISTIC_SYSTEM, user, _HOLISTIC_SCHEMA, host)


def judge_fuzzy(
    input_text: str, rubric: str, intent: dict | None, model: str = DEFAULT_JUDGE_MODEL, host: str | None = None
) -> dict:
    """Judge a fuzzy case against its rubric. Returns {passed, rationale}."""
    user = (
        f"Member's request: {input_text!r}\n"
        f"Rubric: {rubric}\n"
        f"Assistant's interpretation: {intent!r}\n\n"
        "Does it satisfy the rubric?"
    )
    return _call(model, _FUZZY_SYSTEM, user, _FUZZY_SCHEMA, host)
