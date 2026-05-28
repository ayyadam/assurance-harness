# Risk Register — golf-web-app assurance

**Status:** living document — updated as risks are surfaced, mitigated, or accepted.
**Owner:** Adam
**Last updated:** 2026-05-27

This register drives test prioritisation. See [`test-strategy.md` §8](test-strategy.md#8-risk-based-prioritisation) for how it informs decisions.

A row in this register is **a risk to product quality**, not a defect. A defect is logged as a GitHub Issue. A risk is what we're worried *could* happen and what we've done about it.

## How to read

- **L** Likelihood of occurring in production: L (low) / M (medium) / H (high)
- **I** Impact if it does occur: L / M / H
- **Score** = L × I, with H=3, M=2, L=1; ties broken in favour of irreversible failures
- **Status:** open / mitigated / accepted
- **Mitigation:** a brief description with link to the assurance check that addresses it, where one exists

## Active risks

| ID | Risk | L | I | Score | Status | Mitigation |
|---|---|---|---|---|---|---|
| R-001 | Local test environment (in-memory SQLite) is more permissive than CI (Postgres) — FK violations and other strictness gaps mask real bugs locally | M | M | 4 | **mitigated** | SQLAlchemy `Engine.connect` event listener in `golf-web-app/tests/conftest.py` enables `PRAGMA foreign_keys=ON` on SQLite. See [Finding F-001](test-strategy.md#f-001--local-sqlite-hides-foreign-key-violations-that-postgres-catches-in-ci) |
| R-002 | Concurrent bookings of the same tee slot, range bay, or coaching slot cause overbooking or constraint violation | M | H | 6 | **open** | Planned: property-based contract test on booking endpoints (phase 4 Schemathesis), explicit concurrency test in functional layer |
| R-003 | Authentication bypass via session/cookie manipulation or weak password handling | L | H | 3 | **open** | Planned: collaboration with security team / dedicated security review pass; defensive baseline checks in functional layer |
| R-004 | Authorization bypass — a logged-in member accesses admin routes | M | H | 6 | **partially mitigated** | Existing unit tests verify 403/redirect on admin routes when accessed by non-admin (`tests/unit/test_admin_routes.py`); coverage of every admin route not yet complete |
| R-005 | CI lint gate exists in workflow but is not enforced — quality drift accumulates undetected | — | — | — | **mitigated** | Workflow trigger fixed in `chore/ci-pipeline-rework` (was `main`, should have been `master`/`develop`). See [Finding F-002](test-strategy.md#f-002--82-latent-style-violations-exposed-on-first-lint-enforcement) |
| R-006 | No service-boundary contract verification for the JSON API — clients (including the harness) drift from the server's actual behaviour | M | M | 4 | **mitigated** | Schemathesis property-based contract tests in `contract/` run against the live API in CI. Surfaced and fixed 5 spec/behaviour mismatches — see [Finding F-003](test-strategy.md#f-003--contract-testing-surfaced-five-spec-vs-behaviour-mismatches) |
| R-007 | No performance baseline — regressions in latency or throughput land undetected | M | M | 4 | **open** | Planned (phase 5): k6 thresholds-as-code in CI, fail PR on regression beyond budget |
| R-008 | No accessibility validation — WCAG-relevant regressions land undetected | M | M | 4 | **open** | Planned (phase 5): axe-playwright on key pages in CI |
| R-009 | Seed and snapshot data quality drifts over time (date types, FK-able rows, business-rule invariants) | L | M | 2 | **open** | Planned (phase 6): Great Expectations / pandera expectation suites |
| R-010 | GHCR images are not signed — supply chain integrity not provable | L | M | 2 | **accepted** | Out of scope for portfolio demo; would be addressed via cosign + GitHub OIDC in a production setting |
| R-011 | AI booking feature (planned phase 7) hallucinates intent, fabricates names, or selects wrong slots | H | M | 6 | **planned mitigation** | Planned (phase 8): LLM-judge eval against golden set + deterministic guards (slot exists, group size valid, names match input); drift monitoring in observability |
| R-012 | Prompt injection in AI booking feature inputs allows unauthorised actions | M | H | 6 | **planned mitigation** | Planned (phase 8): adversarial inputs in golden set, system-prompt isolation, output validation against domain constraints |
| R-013 | No production observability — failures in a deployed instance go unobserved | M | M | 4 | **open** | Planned (phase 11): Prometheus + Grafana stack monitoring SUT and harness health |
| R-014 | Single point of failure: a self-hosted CI runner tied to a developer machine — CI breaks when the laptop sleeps | L | L | 1 | **mitigated** | Self-hosted runner approach deliberately rejected during phase 0; pipeline runs entirely on hosted runners with a deployability *smoke* check (not a real deploy) |
| R-015 | Test fixtures or seed data contain real PII | L | H | 3 | **mitigated** | All fixture data is synthetic (`testadmin`, `testmember`, `othermember`, `Visitor Test`); the seed file uses placeholder names and phone numbers |
| R-016 | Long-running CI exceeds GitHub free-tier minutes on a private repo | L | L | 1 | **accepted** | Current pipeline is ~3 min/run; would require ~700 pushes/month to brush the 2,000 min/month free limit |
| R-017 | Workflow uses deprecated Node.js 20 actions — will break when GitHub forces Node.js 24 default | M | L | 2 | **mitigated** | Action versions bumped: `actions/checkout@v5`, `actions/setup-python@v6`, `actions/upload-artifact@v5`, `astral-sh/setup-uv@v5` |

## Retired risks

(none yet — risks move here when they cease to apply, e.g. when a system component is removed)

## Update protocol

When a risk is added or changes status, the table above is updated **and** the corresponding section in `test-strategy.md` (Findings to date or layer status) is updated in the same PR. Risks do not live independently of strategy.
