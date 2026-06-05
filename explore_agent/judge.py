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
    "  expected               — The API behaved correctly for this input. This INCLUDES:\n"
    "                           (a) any 4xx refusal (400/401/403/404/409/422) — the API "
    "                           correctly declined a malformed, conflicting, or "
    "                           unauthorised request; a refusal is never a weakness;\n"
    "                           (b) a 2xx with a schema-valid body on an edge or abusive "
    "                           input — gracefully handling weird input is the goal, even "
    "                           when the body is an empty list or the input was an "
    "                           injection-style string the API safely ignored;\n"
    "                           (c) a 2xx whose ids/values differ from what an edge "
    "                           variant 'intended' — path and id parameters are "
    "                           substituted with real seed values before the request is "
    "                           sent, so judge the ACTUAL request+response, not the "
    "                           variant's stated intent.\n"
    "  unexpected_5xx         — The status code is ACTUALLY 5xx, suggesting an unhandled "
    "                           case. Even if the input was abusive, a well-built API "
    "                           should reject it with a 4xx, not crash. Do NOT use this "
    "                           category for any non-5xx status.\n"
    "  schema_drift           — Response body does not match the documented response "
    "                           schema for this status code (missing required field, "
    "                           wrong type, undocumented field, undocumented status code).\n"
    "  business_rule_concern  — The API ACCEPTED something it should have refused, and "
    "                           the body PROVES it: a concrete, evidenced violation such "
    "                           as a past-date booking succeeding (2xx), an action that "
    "                           should be blocked completing, sensitive or other-member "
    "                           data appearing in the body, or internals leaked in an "
    "                           error message. The test is WRONGFUL ACCEPTANCE. A 4xx "
    "                           refusal (especially 409 conflict or 422 validation) is "
    "                           the API doing its job — NOT this category. 'The input was "
    "                           weird/abusive and the API handled it without breaking' is "
    "                           'expected'. Only flag this when you can NAME the specific "
    "                           rule violated and cite the response evidence proving the "
    "                           API let it through.\n"
    "  auth_boundary_concern  — The auth boundary failed to hold. Either: (a) no token "
    "                           or invalid token was accepted on a spec-required-auth "
    "                           endpoint (this case is judged deterministically — you "
    "                           won't see it here); (b) a different member's valid token "
    "                           was accepted on a resource that should be scoped to a "
    "                           SPECIFIC owner, and the response reveals that other "
    "                           owner's data. This does NOT cover identity endpoints "
    "                           like /me (which return the CALLER's data, whoever the "
    "                           caller is) or shared resources like /tee-times or "
    "                           /competitions (which return the same data for every "
    "                           authenticated member).\n"
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
        "THE CALLER IN THIS PROBE IS THAT OTHER MEMBER. They have a valid identity; "
        "the question is whether the endpoint leaks data that should be scoped to a "
        "specific owner who is NOT them.\n\n"
        "Decision rule:\n"
        "  - Identity endpoints (/me, /profile, /account) return data scoped to whoever "
        "    is calling. If the response is the other member's own profile, that's the "
        "    documented behaviour — classify EXPECTED, NOT a concern.\n"
        "  - Shared/catalog endpoints (/tee-times, /competitions, /coaches, public "
        "    schedules, lists) return the same data regardless of which authenticated "
        "    member calls. Any authenticated member seeing this data is by-design — "
        "    classify EXPECTED.\n"
        "  - Owner-scoped reads (/bookings/{id} where {id} belongs to a SPECIFIC "
        "    member, /members/A/private-data) should refuse or filter when the caller "
        "    doesn't own the resource. If the response reveals data tied to a member "
        "    other than the caller, THAT is auth_boundary_concern.\n"
        "  - 4xx/5xx outcomes unrelated to auth (e.g. 409 booking conflict, 422 "
        "    validation) are EXPECTED — auth let the request through; business logic "
        "    refused it.\n\n"
        "The criterion is OWNERSHIP, not 'a different token was used'. If the "
        "response is shared data or the caller's own data, it's not a leak."
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
        f"Actual request sent: {probe.request_method} {probe.request_url}\n"
        f"(the variant rationale is the generator's INTENT; the line above is what was "
        f"actually sent — path/id params already substituted with real seed values)\n"
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
