# Risk Register — golf-web-app assurance

**Status:** living document — updated as risks are surfaced, mitigated, or accepted.
**Owner:** Adam
**Last updated:** 2026-05-29

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
| R-004 | Authorization bypass — a logged-in member accesses admin routes | M | H | 6 | **partially mitigated** | Unit tests verify 403/redirect on admin routes for non-admins (`tests/unit/test_admin_routes.py`); functional test `functional/test_access_control.py` now confirms the boundary holds in a real browser (member bounced off `/admin`, anonymous user sent to login). Per-route coverage of every admin page not yet complete |
| R-005 | CI lint gate exists in workflow but is not enforced — quality drift accumulates undetected | — | — | — | **mitigated** | Workflow trigger fixed in `chore/ci-pipeline-rework` (was `main`, should have been `master`/`develop`). See [Finding F-002](test-strategy.md#f-002--82-latent-style-violations-exposed-on-first-lint-enforcement) |
| R-006 | No service-boundary contract verification for the JSON API — clients (including the harness) drift from the server's actual behaviour | M | M | 4 | **mitigated** | Schemathesis property-based contract tests in `contract/` run against the live API in CI. Surfaced and fixed 5 spec/behaviour mismatches — see [Finding F-003](test-strategy.md#f-003--contract-testing-surfaced-five-spec-vs-behaviour-mismatches) |
| R-007 | No performance baseline — regressions in latency or throughput land undetected | M | M | 4 | **mitigated** | k6 thresholds-as-code in CI (`nonfunctional/performance/api_load.js`) run a ramped load against the read-path API; budget is p95 < 500ms and error rate < 1%, a deliberate SLA-style target. First run caught an N+1 in the tee-times endpoint — see [Finding F-005](test-strategy.md#f-005--performance-gate-caught-an-n1-query-in-the-tee-times-endpoint). A regression beyond budget fails the PR |
| R-008 | No accessibility validation — WCAG-relevant regressions land undetected | M | M | 4 | **mitigated** | axe-core WCAG 2.1 A/AA sweep over six key pages in CI (`nonfunctional/accessibility/`), gating on serious + critical. Surfaced and fixed contrast + missing-label defects — see [Finding F-004](test-strategy.md#f-004--accessibility-sweep-found-wcag-aa-contrast-gaps-and-a-missing-form-label) |
| R-009 | Seed and snapshot data quality drifts over time (date types, FK-able rows, business-rule invariants) | L | M | 2 | **mitigated** | pandera schemas + business-rule invariants validate the live database in CI (`data_quality/`): column contracts (types, nullability, uniqueness, allowed values, ranges) plus invariants like "18 holes with a 1..18 stroke-index permutation" and "tee times within the seeded window". First run passed clean |
| R-010 | GHCR images are not signed — supply chain integrity not provable | L | M | 2 | **accepted** | Out of scope for portfolio demo; would be addressed via cosign + GitHub OIDC in a production setting |
| R-011 | AI booking feature hallucinates intent, fabricates names, or selects wrong slots | H | M | 6 | **partially mitigated** | Architectural boundary delivered (phase 7): the model only emits a structured intent; deterministic code proposes only genuinely bookable slots and the member confirms — a wrong interpretation cannot book, and the UI shows the interpretation so the member can correct it. Manual exploration of the live feature found and fixed two slot-proposal defects — [F-007](test-strategy.md#f-007--assistant-silently-truncated-availability-to-6-of-n-matching-slots) and [F-008](test-strategy.md#f-008--assistant-silently-dropped-a-time-constraint-it-could-not-represent). **Quantified by the phase-8 deterministic eval** ([`ai_evaluation/`](../ai_evaluation/README.md)): a 31-case black-box golden set across 5 candidate models — best `qwen3.6:27b-q4_K_M` 97% / cleanest residuals; currently-deployed `qwen3:8b-fp16` 80% with known relative-date weakness ([report](../ai_evaluation/reports/report.md)). LLM-judge tier (holistic / fuzzy cases) to follow as a second deterministic-eval PR |
| R-012 | Prompt injection in AI booking feature inputs allows unauthorised actions | M | H | 6 | **partially mitigated** | Structured-output boundary delivered (phase 7): the model is constrained to emit a domain intent (date/period/group_size/time-window), never code or actions; deterministic code executes. **Empirically verified by the phase-8 deterministic eval**: 4/4 safety pass *across all 5 candidate models* (8B → 32B) on the adversarial set ([`ai_evaluation/golden_set.yaml`](../ai_evaluation/golden_set.yaml) — injection-delete-database, injection-group-overflow, injection-sql-ish, gibberish robustness). The boundary holds at every model size. A broader adversarial sweep (probe variants beyond 3) is part of the LLM-judge follow-up PR |
| R-013 | No production observability — failures in a deployed instance go unobserved | M | M | 4 | **open** | Planned (phase 11): Prometheus + Grafana stack monitoring SUT and harness health |
| R-014 | Single point of failure: a self-hosted CI runner tied to a developer machine — CI breaks when the laptop sleeps | L | L | 1 | **mitigated** | Self-hosted runner approach deliberately rejected during phase 0; pipeline runs entirely on hosted runners with a deployability *smoke* check (not a real deploy) |
| R-015 | Test fixtures or seed data contain real PII | L | H | 3 | **mitigated** | All fixture data is synthetic (`testadmin`, `testmember`, `othermember`, `Visitor Test`); the seed file uses placeholder names and phone numbers |
| R-016 | Long-running CI exceeds GitHub free-tier minutes on a private repo | L | L | 1 | **accepted** | Current pipeline is ~3 min/run; would require ~700 pushes/month to brush the 2,000 min/month free limit |
| R-017 | Workflow uses deprecated Node.js 20 actions — will break when GitHub forces Node.js 24 default | M | L | 2 | **mitigated** | Action versions bumped: `actions/checkout@v5`, `actions/setup-python@v6`, `actions/upload-artifact@v5`, `astral-sh/setup-uv@v5` |

## Retired risks

(none yet — risks move here when they cease to apply, e.g. when a system component is removed)

## Update protocol

When a risk is added or changes status, the table above is updated **and** the corresponding section in `test-strategy.md` (Findings to date or layer status) is updated in the same PR. Risks do not live independently of strategy.
