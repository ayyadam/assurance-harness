"""Classify each probe response into a finding category, with rationale.

The judgement is intentionally narrow: just four categories, all derivable
from the (endpoint spec, request, response) triple. Severity is bounded to
low / med / high. Anything more elaborate (CVSS-style scoring, exploit
chains) would force the LLM into speculation and produce noise.

The four categories are mutually exclusive — a single response gets one
label. ``expected`` is the dominant outcome; the report only ranks
non-expected findings to the top.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import ollama

from explore_agent.probe import Probe

DEFAULT_MODEL = "qwen2.5:32b-instruct-q4_K_M"

CATEGORIES = ("expected", "unexpected_5xx", "schema_drift", "business_rule_concern")
SEVERITIES = ("low", "med", "high")


@dataclass
class Finding:
    category: str
    severity: str  # ignored when category == "expected"
    rationale: str


_SYSTEM = (
    "You are an exploratory testing agent reviewing one API response for issues. "
    "You are given the endpoint's documented behaviour, the request that was sent, and "
    "the response that came back. Classify the response into exactly ONE category and "
    "give a one-to-two-sentence rationale grounded in specific evidence (status code, "
    "specific response field, schema element, business rule).\n\n"
    "Categories:\n"
    "  expected               — Status and body match the documented behaviour for this "
    "                           input. Validation rejections (4xx) on an edge or abusive "
    "                           input that the schema clearly disallows are 'expected'.\n"
    "  unexpected_5xx         — Server error (5xx) suggests an unhandled case. Even if "
    "                           the input was abusive, a well-built API should reject it "
    "                           with a 4xx, not crash.\n"
    "  schema_drift           — Response body does not match the documented response "
    "                           schema for this status code (missing required field, "
    "                           wrong type, undocumented field, undocumented status code).\n"
    "  business_rule_concern  — Response is technically valid per the schema, but the "
    "                           outcome suggests a business-rule weakness: accepts a "
    "                           past-date booking, returns sensitive data, allows an "
    "                           action that should be blocked, leaks internals via error "
    "                           messages, etc.\n\n"
    "Severity: low | med | high. Use 'low' for 'expected' (it's a placeholder there).\n"
    "Do NOT use this output to speculate about exploits — categorise, ground the "
    "rationale in the evidence, stop."
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


def _user_message(probe: Probe) -> str:
    ep = probe.endpoint
    responses_doc = ep.operation.get("responses", {})
    return (
        f"Endpoint: {ep.method} {ep.path}\n"
        f"Summary:  {ep.summary or '(none)'}\n\n"
        f"Documented responses (status -> shape):\n"
        f"{json.dumps(responses_doc, indent=2)[:3000]}\n\n"
        f"Variant probed: {probe.variant.label} — {probe.variant.rationale}\n"
        f"Request body:\n{json.dumps(probe.request_body, indent=2)}\n\n"
        f"Response status: {probe.status}\n"
        f"Response body (decoded):\n{json.dumps(probe.response_body, indent=2)[:2000]}\n"
        f"Response text (first 1000 chars):\n{probe.response_text[:1000]}\n\n"
        "Classify."
    )


def judge(
    probe: Probe,
    model: str = DEFAULT_MODEL,
    host: str | None = None,
) -> Finding:
    """Classify one probe response."""
    client = ollama.Client(host=host) if host else ollama
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _user_message(probe)},
        ],
        "format": _SCHEMA,
        "options": {"temperature": 0},
    }
    try:
        response = client.chat(think=False, **kwargs)
    except ollama.ResponseError:
        response = client.chat(**kwargs)
    parsed = json.loads(response["message"]["content"])
    return Finding(
        category=parsed["category"],
        severity=parsed["severity"],
        rationale=parsed["rationale"],
    )
