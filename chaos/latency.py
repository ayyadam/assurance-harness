"""Clients for the v2 grey-failure (latency) axis: a Toxiproxy admin-API client
to inject/remove a latency toxic on the DB path, and a Prometheus query client to
confirm the injected latency breaches the p95 SLO panel (the "does the
observability stack actually catch it?" assertion).

Both wrap `requests` but take injectable callables (`request` / `get`) so the
URL/payload construction is unit-testable without a live server. The compose
command builder for the latency topology lives here too."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover - requests is a dev dependency
    requests = None  # type: ignore[assignment]

DEFAULT_TOXIPROXY_API = "http://localhost:8474"
DEFAULT_PROMETHEUS = "http://localhost:9090"
PROXY_NAME = "postgres"
LATENCY_TOXIC = "latency_down"
# prometheus-flask-exporter's request-duration histogram (see observability/).
LATENCY_METRIC = "flask_http_request_duration_seconds"


class Toxiproxy:
    """Minimal Toxiproxy admin-API client (create proxy, add/remove latency)."""

    def __init__(self, api_url: str = DEFAULT_TOXIPROXY_API, request: Callable | None = None) -> None:
        self.api_url = api_url.rstrip("/")
        self._request = request

    def _req(self, method: str, path: str, **kwargs):
        req = self._request or (requests.request if requests else None)
        if req is None:  # pragma: no cover
            raise RuntimeError("requests not installed and no `request` injected")
        return req(method, f"{self.api_url}{path}", timeout=10, **kwargs)

    def ensure_proxy(self, listen: str = "0.0.0.0:5432", upstream: str = "db:5432", name: str = PROXY_NAME):
        """Create the proxy (idempotent: a 409 'already exists' is fine — we only
        need it to exist)."""
        return self._req(
            "POST", "/proxies", json={"name": name, "listen": listen, "upstream": upstream, "enabled": True}
        )

    def add_latency(self, latency_ms: int, jitter_ms: int = 0, name: str = PROXY_NAME, stream: str = "downstream"):
        return self._req(
            "POST",
            f"/proxies/{name}/toxics",
            json={
                "name": LATENCY_TOXIC,
                "type": "latency",
                "stream": stream,
                "attributes": {"latency": latency_ms, "jitter": jitter_ms},
            },
        )

    def remove_latency(self, name: str = PROXY_NAME):
        return self._req("DELETE", f"/proxies/{name}/toxics/{LATENCY_TOXIC}")


class Prometheus:
    """Reads the SUT's p95 request latency from Prometheus — best-effort: any
    error, empty result, or NaN returns None (the caller treats None as
    'insufficient samples', not a failure)."""

    def __init__(self, base_url: str = DEFAULT_PROMETHEUS, get: Callable | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._get = get

    def _instant(self, expr: str) -> float | None:
        get = self._get or (requests.get if requests else None)
        if get is None:  # pragma: no cover
            raise RuntimeError("requests not installed and no `get` injected")
        resp = get(f"{self.base_url}/api/v1/query", params={"query": expr}, timeout=10)
        result = resp.json().get("data", {}).get("result", [])
        if not result:
            return None
        return float(result[0]["value"][1])

    def p95(self, metric: str = LATENCY_METRIC, window: str = "1m") -> float | None:
        expr = f"histogram_quantile(0.95, sum(rate({metric}_bucket[{window}])) by (le))"
        try:
            value = self._instant(expr)
        except Exception:  # noqa: BLE001 - best-effort; any failure => no signal
            return None
        if value is None or value != value:  # None or NaN
            return None
        return value


def latency_compose_cmd(sut_compose: Path, override: Path, *args: str, project: str = "golf-web-app") -> list[str]:
    """`docker compose -p <project> -f <sut> -f <override> <args...>` — the SUT
    compose is first so the project dir (and `build: .` context) resolve to it."""
    return ["docker", "compose", "-p", project, "-f", str(sut_compose), "-f", str(override), *args]
