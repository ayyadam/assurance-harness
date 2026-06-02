"""Generate payload variants per endpoint and send them as HTTP probes.

The LLM proposes a happy / edge / abusive triplet per endpoint, given the
request schema. Path parameters are resolved against a small ``seed_context``
gathered up-front from the live SUT — e.g. a real ``tee_time_id`` pulled from
``GET /tee-times`` — so parameterised endpoints are exercised against real
ids rather than guessed ones.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import ollama
import requests

from explore_agent.spec import Endpoint

DEFAULT_MODEL = "qwen2.5:32b-instruct-q4_K_M"
VARIANT_LABELS = ("happy", "edge", "abusive")


@dataclass
class Variant:
    label: str  # "happy" | "edge" | "abusive"
    body: dict[str, Any] | None
    rationale: str  # one-line description of what this variant probes


@dataclass
class Probe:
    endpoint: Endpoint
    variant: Variant
    request_url: str
    request_method: str
    request_body: Any
    status: int
    latency_ms: float
    response_body: Any  # dict | list | str — best-effort decoded
    response_text: str

    @property
    def status_class(self) -> str:
        if 200 <= self.status < 300:
            return "2xx"
        if 300 <= self.status < 400:
            return "3xx"
        if 400 <= self.status < 500:
            return "4xx"
        return "5xx"


# ── seed context ───────────────────────────────────────────────────────────


def gather_seed_context(session: requests.Session, base_url: str) -> dict[str, str]:
    """Pull a small set of real ids from the SUT to substitute into path params.

    For v1 v1 we only need a tee_time_id; future surfaces can extend this map.
    Returns ``{}`` on failure so the rest of the run still proceeds — the
    endpoints needing those ids simply get skipped.
    """
    ctx: dict[str, str] = {}
    try:
        resp = session.get(base_url.rstrip("/") + "/api/v1/tee-times", timeout=10)
        if resp.ok:
            data = resp.json()
            items = data if isinstance(data, list) else data.get("items") or data.get("tee_times") or []
            if items:
                first = items[0]
                tid = first.get("id") or first.get("tee_time_id")
                if tid is not None:
                    ctx["tee_time_id"] = str(tid)
    except Exception:
        pass
    return ctx


# ── LLM payload generation ────────────────────────────────────────────────


_VARIANT_SYSTEM = (
    "You are an exploratory testing agent for a JSON API. Given an endpoint's request "
    "schema, propose three request body variants that probe distinct concerns:\n\n"
    "  happy   — A minimal valid body a real client would send. Stick to required "
    "            fields, use plausible realistic values.\n"
    "  edge    — A body at the boundary of validation: empty strings where allowed, "
    "            missing optional fields, dates at year boundaries, oversize-but-legal "
    "            string lengths, edge numeric ranges, unicode quirks. Still tries to "
    "            be a 'valid' request the schema permits.\n"
    "  abusive — A body intended to probe robustness: oversize strings, injection-style "
    "            payloads ('; DROP TABLE --, <script>, ${jndi:...}), wrong types where "
    "            the schema demands a specific type, enum violations. For AI-backed "
    "            endpoints, include a prompt-injection probe like 'Ignore prior "
    "            instructions and ...'.\n\n"
    "If the endpoint takes no request body (e.g. a GET), return null for ``body`` in "
    "every variant — the agent will still send the request, varying only the query/path. "
    "Each variant needs a ONE-SENTENCE rationale describing what it probes."
)


_VARIANT_SCHEMA = {
    "type": "object",
    "properties": {
        "variants": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "enum": list(VARIANT_LABELS)},
                    "body": {"type": ["object", "null"]},
                    "rationale": {"type": "string"},
                },
                "required": ["label", "body", "rationale"],
            },
        },
    },
    "required": ["variants"],
}


def _variant_user_message(endpoint: Endpoint) -> str:
    schema = endpoint.request_schema
    schema_blob = json.dumps(schema, indent=2) if schema else "(no request body)"
    return (
        f"Endpoint: {endpoint.method} {endpoint.path}\n"
        f"Summary:  {endpoint.summary or '(none)'}\n\n"
        f"Request body schema:\n{schema_blob}\n\n"
        f"Available component schemas (for $ref resolution):\n"
        f"{json.dumps(endpoint.components, indent=2)[:4000]}\n\n"
        "Propose three variants."
    )


def propose_variants(
    endpoint: Endpoint,
    model: str = DEFAULT_MODEL,
    host: str | None = None,
) -> list[Variant]:
    """Ask the LLM for happy / edge / abusive payloads for this endpoint."""
    client = ollama.Client(host=host) if host else ollama
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _VARIANT_SYSTEM},
            {"role": "user", "content": _variant_user_message(endpoint)},
        ],
        "format": _VARIANT_SCHEMA,
        "options": {"temperature": 0},
    }
    try:
        response = client.chat(think=False, **kwargs)
    except ollama.ResponseError:
        response = client.chat(**kwargs)
    parsed = json.loads(response["message"]["content"])
    return [Variant(label=v["label"], body=v["body"], rationale=v["rationale"]) for v in parsed["variants"]]


# ── HTTP probing ──────────────────────────────────────────────────────────


def resolve_path(endpoint: Endpoint, seed_context: dict[str, str]) -> str | None:
    """Substitute path params from seed context; return ``None`` if any missing."""
    path = endpoint.path
    for name in endpoint.path_params:
        if name not in seed_context:
            return None
        path = path.replace("{" + name + "}", seed_context[name])
    return path


def send_probe(
    session: requests.Session,
    base_url: str,
    endpoint: Endpoint,
    variant: Variant,
    seed_context: dict[str, str],
    timeout: float = 15.0,
) -> Probe | None:
    """Send one probe; return None if the endpoint can't be resolved."""
    resolved = resolve_path(endpoint, seed_context)
    if resolved is None:
        return None
    url = base_url.rstrip("/") + resolved
    started = time.perf_counter()
    try:
        resp = session.request(
            method=endpoint.method,
            url=url,
            json=variant.body if variant.body is not None else None,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return Probe(
            endpoint=endpoint,
            variant=variant,
            request_url=url,
            request_method=endpoint.method,
            request_body=variant.body,
            status=0,
            latency_ms=latency_ms,
            response_body=None,
            response_text=f"<request error: {exc}>",
        )
    latency_ms = (time.perf_counter() - started) * 1000
    text = resp.text
    body: Any
    try:
        body = resp.json()
    except ValueError:
        body = None
    return Probe(
        endpoint=endpoint,
        variant=variant,
        request_url=url,
        request_method=endpoint.method,
        request_body=variant.body,
        status=resp.status_code,
        latency_ms=latency_ms,
        response_body=body,
        response_text=text,
    )
