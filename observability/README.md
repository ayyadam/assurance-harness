# Observability stack

Phase 11 of the assurance roadmap. Local Prometheus + Grafana stack that scrapes the SUT (golf-web-app) and visualises HTTP request rate, error rate, and latency. Closes R-013 (no production observability).

The k6 performance gate ([nonfunctional/performance/](../nonfunctional/performance/)) measures cost-of-feature **pre-merge**; this stack watches cost-and-correctness **post-deploy**. Same signals, different point in the SDLC.

## Architecture

```
observability/
├── docker-compose.yml              # Prometheus + Grafana
├── prometheus/
│   └── prometheus.yml              # scrape config
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/
│   │   │   └── prometheus.yml      # Prometheus datasource (provisioned)
│   │   └── dashboards/
│   │       └── dashboards.yml      # dashboard provider (provisioned)
│   └── dashboards/
│       └── sut-overview.json       # the SUT health dashboard
└── evidence/
    ├── grafana-sut-overview.png    # screenshot — committed evidence
    └── prometheus-targets.png      # screenshot — Prometheus targets healthy
```

Decisions worth calling out:

- **Two independent stacks talking via the host gateway.** The SUT compose lives in `golf-web-app/`, this stack lives in `testing-system/observability/`. They run side-by-side without a shared compose network — Prometheus reaches the SUT via `host.docker.internal:5000`. Lets each repo own its own runtime concerns without cross-coupling.
- **Everything provisioned, nothing clicked.** Prometheus config, Grafana datasource, dashboard provider, and dashboard JSON are all version-controlled and loaded at container start. There is no "I made some changes in the Grafana UI" state — `docker compose up -d` from a clean clone reproduces the exact dashboard reviewed here.
- **Anonymous viewer enabled.** `GF_AUTH_ANONYMOUS_ENABLED=true` (Viewer role) so the panel can browse without credentials; `admin/admin` still works for editing. Local stack only — no public exposure.
- **7-day retention.** Prometheus is configured with `--storage.tsdb.retention.time=7d` — enough to support a few PR cycles, short enough that the local volume doesn't grow indefinitely for a demo stack.

## Quick start

The SUT must be up first (separate compose in the golf-web-app repo). The SUT exposes `/metrics` via `prometheus-flask-exporter` — see [golf-web-app PR #13](https://github.com/ayyadam/golf-web-app/pull/13).

```bash
# 1. Bring up the SUT
cd ../golf-web-app && docker compose up -d

# 2. Bring up the observability stack
cd ../testing-system/observability && docker compose up -d

# 3. Open the dashboards
#    Grafana:    http://localhost:3000  (anonymous viewer or admin/admin)
#    Dashboard:  http://localhost:3000/d/sut-overview
#    Prometheus: http://localhost:9090
#    Targets:    http://localhost:9090/targets
```

Generate some traffic against the SUT (browse to http://localhost:5000 or hit endpoints with curl) and watch the panels update within ~15s (the scrape interval).

## What's on the dashboard

The single `SUT overview — golf-web-app` dashboard is laid out as **headline stats on top, time-series detail below**:

| Panel | Source query (PromQL) | Why it's there |
|---|---|---|
| Requests/sec (1m) | `sum(rate(flask_http_request_total{service="sut"}[1m]))` | Baseline activity. If this drops to zero unexpectedly, the SUT isn't serving. |
| Error rate (1m) | `(sum(rate(...status=~"5.."[1m])) or vector(0)) / clamp_min(sum(rate(...)[1m]), 1e-9)` | SRE-style 5xx error ratio. Thresholds: green `<1%`, yellow `1–5%`, red `>5%`. 4xx is deliberately excluded — those are client-driven, not server failures. |
| p95 latency (5m) | `histogram_quantile(0.95, sum(rate(flask_http_request_duration_seconds_bucket{service="sut"}[5m])) by (le))` | Thresholds aligned to k6's gate budget: green `<250ms`, yellow `250–500ms`, red `>500ms`. The same number the k6 perf job asserts pre-merge. |
| App | `flask_app_info{service="sut"}` | Version gauge. Shows the SUT is alive and which build is responding. |
| Requests/sec by path | `sum(rate(flask_http_request_duration_seconds_count{service="sut"}[1m])) by (path)` | Per-endpoint traffic. Detects shifts in load distribution. |
| Latency percentiles (overall) | `histogram_quantile(p, ...)` for p50/p95/p99 | Distribution shape — a widening p99/p95 gap signals tail latency outliers. |
| Response status mix | `sum(rate(flask_http_request_total{service="sut"}[1m])) by (status)` | Stacked bars of 2xx/3xx/4xx/5xx. Visualises everything the headline rates summarise. |
| p95 latency by path | `histogram_quantile(0.95, ... by (path, le))` | Per-endpoint p95 — the panel that would have surfaced [F-005's N+1](../docs/test-strategy.md#f-005) the moment it landed. |

## SLO targets and how they connect to the rest of the harness

The dashboard's thresholds aren't arbitrary — they match the gates the harness already enforces pre-merge:

| Signal | SLO target on the dashboard | Pre-merge enforcement |
|---|---|---|
| p95 read-path latency | `< 250ms` green / `< 500ms` yellow | [k6 perf gate](../nonfunctional/performance/api_load.js) p95 < 500ms — set as a `http_req_duration` threshold |
| 5xx error rate | `< 1%` green / `< 5%` yellow | k6 gate `http_req_failed < 1%` |
| WCAG conformance | not on this dashboard — pre-merge only | [axe-core sweep](../nonfunctional/accessibility/) gates serious + critical |
| API contract conformance | not on this dashboard — pre-merge only | [Schemathesis](../contract/) gates 422 on contract drift |
| Data shape | not on this dashboard — pre-merge only | [pandera](../data_quality/) gates per-column contracts |

The story this lays out: pre-merge gates prevent regressions from landing on `develop`; this stack catches what would still slip through in deploy. Same SLOs, two enforcement points.

## Evidence

[`evidence/grafana-sut-overview.png`](evidence/grafana-sut-overview.png) — the dashboard rendered with real traffic against the SUT (0.51 req/s, 0.00% 5xx, ~5ms p95). Captured against a freshly-built SUT and a freshly-provisioned stack from this repo's clone — no manual click-through state involved. The screenshot is reproducible from `docker compose up -d` in both repos.

[`evidence/prometheus-targets.png`](evidence/prometheus-targets.png) — Prometheus's targets page showing both scrape targets healthy.

## What's NOT in v1 (deferred)

- **Alertmanager / actual alerting.** Without a real alert sink (Slack, PagerDuty), Alertmanager would fire to nowhere — demo theatre rather than assurance. v2 candidate when there's a real receiver.
- **Loki for log aggregation.** The strategy mentions "Prometheus + Grafana + Loki" for production observability. For v1, metrics carry the story without the extra moving piece. v2 candidate.
- **Tracing (OpenTelemetry / Jaeger).** Useful for diagnosing tail latency by request path. v2 candidate.
- **Multi-environment config (dev vs prod targets).** This stack scrapes one local SUT.

## Roadmap (this stack)

- [x] v1: Prometheus + Grafana scraping the SUT's `/metrics`, single dashboard, SLO thresholds aligned to k6 gate, committed evidence
- [ ] v2 candidates: Loki for logs; Alertmanager when a real sink exists; tracing for per-request diagnosis
