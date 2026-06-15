# Resilience / chaos evaluation — golf-web-app

- **Run:** 2026-06-15T11:13:14
- **SUT:** http://localhost:5000 (compose stack at `D:\Dev\Repos\golf-web-app`)
- **Method:** steady-state hypothesis → inject one fault → assert bounded degradation + automatic recovery. One representative fault per failure *axis*.
- **CI posture:** local-only (mutates a live stack); scenario *logic* is gate-tested in `tests/test_chaos_scenarios.py`.
- **Fault-model note:** process death is injected *inside* the container (signalling the app's PID 1), not via `docker kill` — Docker treats an operator kill as a manual stop that the restart policy ignores, so killing the container would report a false 'no recovery'.

## Summary

**2/3 scenarios passed.**

| Scenario | Failure axis | Result |
|---|---|---|
| DB outage | below the app — dependency gone | ❌ failed |
| Process kill | the app itself — process death | ✅ passed |
| DB latency (grey failure) | between app & dependency — dependency slow | ✅ passed |

## DB outage — ❌ failed

_Hypothesis:_ With Postgres paused, /course fails fast with a clean 5xx (no traceback), / stays 200, and the app recovers automatically on unpause.

| Step | Expected | Observed | Held |
|---|---|---|---|
| steady state | /course == 200 before fault | HTTP 200 | ✅ |
| degrade — data route fails fast | /course returns a clean 5xx within timeout, no leaked traceback | hang/timeout | ❌ |
| partial availability — static route | / stays 200 while the DB is down (graceful degradation, not total outage) | HTTP 200 | ✅ |
| auto-recovery | /course returns to 200 within 30s of unpause, no manual restart | HTTP 200 after ~0s | ✅ |

## Process kill — ✅ passed

_Hypothesis:_ When the web process dies, the restart policy returns /course to 200 with no manual intervention (RestartCount increments), and data reads stay consistent.

| Step | Expected | Observed | Held |
|---|---|---|---|
| steady state | /course == 200 before fault | HTTP 200 | ✅ |
| auto-restart recovery | restart policy returns /course to 200 within 60s, no manual intervention | HTTP 200 after ~2s | ✅ |
| restart policy engaged | container RestartCount increments — recovery was the policy, not a coincidence | RestartCount 2 → 3 | ✅ |
| clean DB reconnect | data route serves consistent data after restart (pool re-established) | HTTP 200 | ✅ |

## DB latency (grey failure) — ✅ passed

_Hypothesis:_ With ~600ms injected on the DB path, /course stays 200 (correctness preserved) but breaches the 500ms p95 SLO, the breach is visible in Prometheus, and latency returns to baseline on removal.

| Step | Expected | Observed | Held |
|---|---|---|---|
| steady state | /course == 200 and under the 500ms SLO before fault | HTTP 200 in 19ms | ✅ |
| graceful degradation under latency | /course still 200 but slower than the 500ms SLO (degrades, not breaks) | all 200, median 1824ms | ✅ |
| SLO breach observed (Prometheus) | the injected latency breaches the p95 SLO panel — the observability stack catches the grey failure | p95 2425ms vs 500ms SLO | ✅ |
| recovery | /course returns to 200 under the 500ms SLO once the toxic is removed | HTTP 200 in 4ms | ✅ |

## Excluded by design (scope discipline)

Chaos testing balloons into a fault-injection framework unless bounded. This layer tests *one representative per real failure axis*; the following are deliberately out of scope:

| Not tested | Why |
|---|---|
| Ollama / AI dependency down | Already covered by design: the booking assistant degrades to a deterministic stub. That fallback *is* the resilience pattern, so it is asserted elsewhere, not re-broken here. |
| Resource exhaustion (CPU / memory / disk) | The SUT has no defined behaviour under resource pressure to assert against — injecting it would be vandalism, not a test with a pass/fail. |
| Observability stack down (Prometheus / Grafana) | Non-critical-path: losing dashboards does not affect user-facing correctness, so it has no graceful-degradation contract to test. |
| Multi-fault / combinatorial chaos | Non-reproducible and a maturity level beyond a portfolio demo; v1 injects one fault at a time with a bounded blast radius. |
| Latency permutations (1s / 2s / 5s / …) | Combinatorial padding. The grey-failure *axis* is covered once (v2, toxiproxy) with a value chosen to breach the SLO; more values add runtime, not information. |

## Roadmap

- **v2 — grey-failure axis (shipped):** Postgres latency injected via [toxiproxy](https://github.com/Shopify/toxiproxy) between `web` and `db` — asserts graceful degradation under slowness **and** that the p95 latency SLO breaches in Prometheus (the observability stack catching a slow dependency, not just an outage). Run with `--latency`.
- **Possible v3:** alerting-side assertion (Alertmanager fires on the SLO breach) once a real alert sink exists — pairs with the deferred Loki/Alertmanager observability work.
