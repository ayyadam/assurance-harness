# Chaos / resilience testing (B4)

Fault-injects the **running** `golf-web-app` compose stack and asserts *graceful
degradation* and *automatic recovery* — the risk surface every healthy-path test
(functional, E2E, metamorphic, k6 load) leaves untouched. It is the failure-side
partner to the k6 load gate (*fast under load?* ↔ *graceful under failure?*) and
the thing that makes the Prometheus/Grafana stack earn its keep (*does an
injected incident actually surface?*).

## The discipline: one representative per failure *axis*

Chaos testing degenerates into "break random things" without a bounding rule.
The rule here: **inject one representative fault per distinct failure axis the
architecture can exhibit, and only faults with a pre-stated correct behaviour.**
The SUT's architecture (Flask `web` + Postgres `db` + non-critical observability)
collapses to three axes:

| Axis | Fault | Scenario | Distinct property proved |
|---|---|---|---|
| Below the app — dependency *gone* | `docker compose pause db` | `db-outage` | data route fails *fast & clean* (5xx, no traceback), static route stays up, auto-recovers on unpause |
| The app itself — process *death* | in-container kill of the app's PID 1 | `process-kill` | `restart: unless-stopped` recovers to 200 with no manual intervention (RestartCount increments); DB reconnects cleanly |
| Between app & dependency — dependency *slow* (grey failure) | toxiproxy latency (~600ms) | `db-latency` (v2) | stays 200 but breaches the 500ms p95 SLO (degrades, doesn't break) **and** the breach is confirmed live in Prometheus |

Each axis forces a *different* assertion — an outage is easy to handle (you know
it's down); a grey failure is the nasty one (health checks pass, the system dies
slowly); process death is a third thing (recovery + state integrity). That's why
it's these three and not a dozen latency values. All three are shipped.

> **Grey-failure note (v2):** the latency axis repoints the DB connection through
> a toxiproxy sidecar (`web → toxiproxy → db`) on the **primary :5000 stack** — so
> the Prometheus that already scrapes :5000 sees the degradation — then asserts
> the p95 latency SLO breaches *live in Prometheus*, not just app-side. That is
> what makes the observability stack earn its keep: an injected incident
> measurably moves the SLO panel. The Prometheus step is **best-effort**
> (confirm-or-abstain: it fails only on a contradiction, never on thin samples).

> **Fault-model note (process death):** the crash is injected *inside* the
> container (signalling the app's PID 1), **not** via `docker kill`/`compose
> kill`. Docker flags an operator kill as a manual stop, so the restart policy
> deliberately ignores it — killing the container would test the wrong thing and
> report a false "no recovery". Getting this right is the difference between a
> real resilience finding and a Docker-semantics artifact.

What is **deliberately not** tested (and why) is recorded in the report itself —
the *shape* of the testing is part of the evidence.

## Running it

Local-only — it pauses and SIGKILLs live containers, so it never runs in hosted
CI. Bring the SUT up first (sibling checkout), then:

```bash
# in golf-web-app:
docker compose up -d --build
docker compose exec -T web python seed.py   # /course needs Hole rows
# (for the v2 latency axis, also bring up the observability stack so the
#  Prometheus SLO-breach can be asserted: cd observability && docker compose up -d)

# in assurance-harness:
uv run python -m chaos.run                       # the two v1 axes (non-invasive)
uv run python -m chaos.run --scenario db-outage  # one v1 scenario
uv run python -m chaos.run --latency             # also the v2 grey-failure axis (INVASIVE: recreates + restores the stack)
```

The committed report is from `--latency` (all three axes). The v2 path repoints
`web` through toxiproxy via [`compose.latency.yml`](compose.latency.yml), runs the
grey-failure scenario, then **always restores the normal stack** (toxiproxy
removed, `web` back on `db:5432`, the SUT's auto override reapplied).

Writes `chaos/reports/report.{md,json}` (committed evidence). Exit code is
non-zero if any scenario fails, so a runner notices — but the report is always
written first. A *failed* scenario is a genuine resilience finding, not a harness
error.

## What's gate-tested vs local

The scenario **logic** (probe classification, recovery polling, the full
steady-state → fault → recover flow) is unit-tested with injected fakes in
[`tests/test_chaos_scenarios.py`](../tests/test_chaos_scenarios.py) — no Docker,
no live SUT — so it runs in the standard pytest gate. Only the **live** run needs
the stack up, and that is the local-only evidence step above.

## Files

| File | Role |
|---|---|
| `faults.py` | `probe()` + `ProbeResult` (classifies 200 / clean-5xx / hang / refused / leaked-traceback); `ComposeController` (pause/unpause/crash/up + `restart_count`); `wait_for_recovery()` |
| `latency.py` | v2 grey-failure clients: `Toxiproxy` (admin-API latency toxic), `Prometheus` (p95 SLO query), `latency_compose_cmd` |
| `compose.latency.yml` | v2 override: toxiproxy sidecar + `web` repointed through `toxiproxy:5432` |
| `scenarios.py` | `scenario_db_outage`, `scenario_process_kill`, `scenario_db_latency` — each a steady-state hypothesis returning a `ScenarioResult` |
| `run.py` | CLI + markdown/JSON report (exclusions table + roadmap); owns the v2 latency-topology lifecycle |
| `reports/` | committed evidence artifact |
