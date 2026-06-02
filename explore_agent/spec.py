"""Fetch + parse the SUT's OpenAPI spec into a flat list of probable endpoints.

We deliberately exclude two paths from probing:

  * ``/metrics`` — operational endpoint exposed by ``prometheus-flask-exporter``
    (phase 11). Not a product surface and not described by the v1 spec after
    [F-010](../docs/test-strategy.md#f-010); skip even if it leaks back in.
  * ``/api/v1/auth/token`` — the agent uses this endpoint to obtain credentials
    for every other probe, so probing it would either burn the auth path or
    require special-casing. Login endpoints are better tested by the dedicated
    contract + functional layers; the exploratory agent's value is downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests

EXCLUDED_PATHS = frozenset({"/metrics", "/api/v1/auth/token"})
PROBED_METHODS = frozenset({"get", "post", "put", "patch", "delete"})


@dataclass
class Endpoint:
    method: str  # uppercase
    path: str  # OpenAPI-templated, e.g. /api/v1/tee-times/{tee_time_id}
    summary: str
    operation: dict[str, Any] = field(repr=False)  # raw operation object from the spec
    components: dict[str, Any] = field(repr=False)  # full components.schemas for $ref resolution

    @property
    def signature(self) -> str:
        return f"{self.method} {self.path}"

    @property
    def request_schema(self) -> dict[str, Any] | None:
        body = self.operation.get("requestBody") or {}
        content = (body.get("content") or {}).get("application/json") or {}
        return content.get("schema")

    @property
    def path_params(self) -> list[str]:
        return [p["name"] for p in self.operation.get("parameters", []) if p.get("in") == "path"]


def fetch_spec(base_url: str, timeout: float = 15.0) -> dict[str, Any]:
    """Fetch the OpenAPI document from the live SUT."""
    url = base_url.rstrip("/") + "/api/v1/openapi.json"
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def parse_endpoints(spec: dict[str, Any]) -> list[Endpoint]:
    """Flatten ``paths`` × methods into ``Endpoint`` records, minus exclusions."""
    components = (spec.get("components") or {}).get("schemas", {})
    endpoints: list[Endpoint] = []
    for path, path_item in (spec.get("paths") or {}).items():
        if path in EXCLUDED_PATHS:
            continue
        for method, operation in path_item.items():
            if method not in PROBED_METHODS:
                continue
            endpoints.append(
                Endpoint(
                    method=method.upper(),
                    path=path,
                    summary=operation.get("summary", ""),
                    operation=operation,
                    components=components,
                )
            )
    return endpoints
