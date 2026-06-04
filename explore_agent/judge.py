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

CATEGORIES = (
    "expected",
    "unexpected_5xx",
    "schema_drift",
    "business_rule_concern",
    "auth_boundary_concern",
    "documented_public_endpoint",
)
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
    "                           messages, etc.\n"
    "  auth_boundary_concern  — The request used a credential mode the endpoint should "
    "                           reject or restrict (no token, an invalid token, or another "
    "                           member's token on an owner-restricted resource), and the "
    "                           response indicates the boundary failed to hold (2xx where "
    "                           a 401/403 was expected, or another member's data returned "
    "                           when ownership should restrict it).\n"
    "  documented_public_endpoint — The spec documents this endpoint as accepting "
    "                           unauthenticated traffic and the response is consistent "
    "                           with that. Informational: surfaces a documented design "
    "                           choice for reviewer confirmation, NOT a finding.\n\n"
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


_AUTH_MODE_CONTEXT = {
    "default": (
        "Auth mode: default — the seeded member's bearer token was sent. Standard "
        "happy/edge/abusive classification applies."
    ),
    "unauth": (
        "Auth mode: unauth — NO Authorization header was sent. A correctly-secured "
        "endpoint must reject this with 401/403. 2xx here is an auth bypass."
    ),
    "wrong_creds": (
        "Auth mode: wrong_creds — an invalid bearer token was sent. A correctly-secured "
        "endpoint must reject this with 401/403. 2xx here is an auth bypass."
    ),
    "other_member": (
        "Auth mode: other_member — a DIFFERENT seeded member's valid token was sent. "
        "Endpoints that return data scoped to the caller (e.g. /me) are expected to "
        "return that other member's data, which is correct behaviour. Endpoints that "
        "expose a specific resource id should not leak resources owned by a different "
        "member without an authorisation check. Read carefully and classify based on "
        "what the response reveals."
    ),
}


def _user_message(probe: Probe) -> str:
    ep = probe.endpoint
    responses_doc = ep.operation.get("responses", {})
    auth_note = _AUTH_MODE_CONTEXT.get(probe.auth_mode, "")
    return (
        f"Endpoint: {ep.method} {ep.path}\n"
        f"Summary:  {ep.summary or '(none)'}\n\n"
        f"{auth_note}\n\n"
        f"Documented responses (status -> shape):\n"
        f"{json.dumps(responses_doc, indent=2)[:3000]}\n\n"
        f"Variant probed: {probe.variant.label} — {probe.variant.rationale}\n"
        f"Request body:\n{json.dumps(probe.request_body, indent=2)}\n\n"
        f"Response status: {probe.status}\n"
        f"Response body (decoded):\n{json.dumps(probe.response_body, indent=2)[:2000]}\n"
        f"Response text (first 1000 chars):\n{probe.response_text[:1000]}\n\n"
        "Classify."
    )


def deterministic_auth_finding(probe: Probe) -> Finding:
    """Mechanical classification for unauth / wrong_creds probes — spec-aware.

    The rule is unambiguous when the endpoint's documented security stance
    is known: a 2xx response on an *unauth/wrong_creds* probe is only an
    ``auth_boundary_concern`` when the spec says auth was required. If the
    spec documents the endpoint as public, a 2xx is what the contract
    promises — surfaced as ``documented_public_endpoint`` (informational,
    not a finding) so a reviewer can still confirm intent.

    The semantic shift introduced in F-020: "the agent flags spec/impl
    auth drift" rather than "the agent flags any anonymous 2xx".
    """
    is_auth_required = probe.endpoint.is_auth_required

    if probe.status in (401, 403):
        return Finding(
            category="expected",
            severity="low",
            rationale=(f"Endpoint correctly rejected the {probe.auth_mode} probe with {probe.status}."),
        )
    if 200 <= probe.status < 300:
        if is_auth_required:
            return Finding(
                category="auth_boundary_concern",
                severity="high",
                rationale=(
                    f"Spec/impl auth drift: the OpenAPI spec marks this endpoint as "
                    f"requiring auth, but it accepted a {probe.auth_mode} request and "
                    f"returned {probe.status}. Either the impl is missing an auth check "
                    "or the spec's security stanza is wrong."
                ),
            )
        return Finding(
            category="documented_public_endpoint",
            severity="low",
            rationale=(
                f"Spec documents this endpoint as accepting unauthenticated traffic "
                f"and it returned {probe.status} on the {probe.auth_mode} probe — "
                "consistent with the documented contract. Surfaced for reviewer "
                "confirmation that public access is the intended design."
            ),
        )
    if probe.status >= 500:
        return Finding(
            category="unexpected_5xx",
            severity="high",
            rationale=(
                f"Endpoint returned {probe.status} on a {probe.auth_mode} probe; "
                "auth-rejection paths should return a controlled 4xx, not crash."
            ),
        )
    return Finding(
        category="expected",
        severity="low",
        rationale=(
            f"Endpoint returned {probe.status} on a {probe.auth_mode} probe — "
            "non-2xx, non-5xx outcome treated as the documented rejection path."
        ),
    )


def judge(
    probe: Probe,
    model: str = DEFAULT_MODEL,
    host: str | None = None,
) -> Finding:
    """Classify one probe response.

    For ``unauth`` and ``wrong_creds`` probes the rule is mechanical and we use
    ``deterministic_auth_finding`` directly. All other modes (default, other_member)
    go through the LLM judge.
    """
    if probe.auth_mode in ("unauth", "wrong_creds"):
        return deterministic_auth_finding(probe)
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
