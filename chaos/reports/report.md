# Resilience / chaos evaluation — golf-web-app

- **Run:** 2026-06-15T09:56:23
- **SUT:** http://localhost:5000 (compose stack at `D:\Dev\Repos\golf-web-app`)
- **Method:** steady-state hypothesis → inject one fault → assert bounded degradation + automatic recovery. One representative fault per failure *axis*.
- **CI posture:** local-only (mutates a live stack); scenario *logic* is gate-tested in `tests/test_chaos_scenarios.py`.
- **Fault-model note:** process death is injected *inside* the container (signalling the app's PID 1), not via `docker kill` — Docker treats an operator kill as a manual stop that the restart policy ignores, so killing the container would report a false 'no recovery'.

## Summary

**1/2 scenarios passed.**

| Scenario | Failure axis | Result |
|---|---|---|
| DB outage | below the app — dependency gone | ❌ failed |
| Process kill | the app itself — process death | ✅ passed |

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
| restart policy engaged | container RestartCount increments — recovery was the policy, not a coincidence | RestartCount 1 → 2 | ✅ |
| clean DB reconnect | data route serves consistent data after restart (pool re-established) | HTTP 200 | ✅ |

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

- **v2 — grey-failure axis:** inject Postgres latency via [toxiproxy](https://github.com/Shopify/toxiproxy) between `web` and `db`; assert graceful degradation under slowness **and** that the latency SLO/Grafana panel breaches (proving the observability stack catches a slow dependency, not just an outage).
