"""Deterministic register pre-filter for risk_agent.

Classifies a PR diff by which file paths it touches and returns the subset of
register risks that can plausibly be raised by changes to those paths. The
agent then only judges relevance among the pre-qualified set.

Why this exists: phase 9 v4 v2 (F-015) documented a ceiling on what pure
prompt + register-text tuning can achieve. The agent's row-matching pass
treats all 19 rows as candidates on every diff and over-pulls keyword-adjacent
rows it can't reliably exclude through prompt rules alone. Phase 13's bet is
that *layer classification* is not genuinely ambiguous — a CSS file is a CSS
file, a workflow YAML is a workflow YAML — and so it belongs in deterministic
Python, not in the LLM. The agent's reserved for the *actually fuzzy* judgment
of relevance level (2 vs 3) and rationale within a small pre-qualified set.

Mapping shape: each entry is (R-ID, [glob patterns], rationale). Patterns
match against the file paths emitted by `git diff` (which are relative to the
SUT repo root, e.g. `app/routes/member.py`, `.github/workflows/ci-cd.yml`).
Each entry carries a comment explaining *why* this layer can raise this risk
— the mapping is itself defendable, like the golden set is.

Failure mode: a hand-authored mapping can miss a file layout we didn't
anticipate. The fallback rule (no pattern matches any file → return full
register) preserves recall in the unknown case: better the agent over-pulls
than that the pre-filter silently excludes a relevant row. v1 prefers
false-positive in the filter.
"""

from __future__ import annotations

import fnmatch

from risk_agent.diff import DiffBundle
from risk_agent.register import Risk

# Each entry: (R-ID, glob patterns, rationale).
#
# Patterns match file paths exactly via fnmatch with `**` extended to mean
# "any number of intermediate directory segments". See `_path_matches`.
#
# When adding a pattern: prefer the most specific path that still captures
# the genuine mechanism. R-002 lives in the booking-create code path, not
# in *every* route handler; R-008 lives in the rendered UI, not in *every*
# template (but templates are uniformly UI in this SUT, so the broad pattern
# is honest).
_MAPPING: list[tuple[str, list[str], str]] = [
    (
        "R-001",
        ["tests/conftest.py", "app/models/**"],
        "SQLite FK pragma is set in tests/conftest.py; model changes can "
        "introduce new FK relations whose enforcement diverges between "
        "in-memory SQLite (local) and Postgres (CI).",
    ),
    (
        "R-002",
        [
            "app/routes/member.py",
            "app/routes/visitor.py",
            "app/services/booking_service.py",
            "app/models/**",
        ],
        "Booking-create check-then-create pattern lives in the route "
        "handlers that own /book POSTs, the service module those handlers "
        "delegate to, and the models that define uniqueness constraints. "
        "Refactors that relocate the pattern still touch one of these.",
    ),
    (
        "R-003",
        [
            "app/auth/**",
            "app/api/views.py",
            "app/api/schemas.py",
        ],
        "Authentication path: blueprint-level handlers in app/auth, the "
        "API's /auth/token endpoint in api/views, and the input schemas "
        "that validate credentials before the auth check runs.",
    ),
    (
        "R-004",
        [
            "app/routes/admin.py",
            "app/auth/**",
            "app/models/**",
        ],
        "Admin authz boundary: admin-only routes, the login_required/"
        "admin_required decorators in app/auth, and the Member model's "
        "membership_type that drives the predicate.",
    ),
    (
        "R-005",
        [".github/workflows/**"],
        "Whether the CI lint gate fires is purely a workflow configuration "
        "concern. No application change can raise this.",
    ),
    (
        "R-006",
        [
            "app/api/**",
            "app/__init__.py",
        ],
        "Contract surface: every endpoint definition + schema lives under "
        "app/api/; spec_processor (which prunes /metrics from the published "
        "spec) lives in app/__init__.py.",
    ),
    (
        "R-007",
        [
            "app/models/**",
            "app/routes/**",
            "app/api/**",
            "app/services/**",
        ],
        "Performance/latency risk lives wherever a query pattern can "
        "regress: model query helpers (N+1 lazy loading), route handlers "
        "that compose queries, the API surface that orchestrates them, "
        "and service modules that batch or paginate.",
    ),
    (
        "R-008",
        [
            "app/templates/**",
            "app/static/css/**",
            "app/static/js/**",
        ],
        "Rendered UI surface: Jinja templates, CSS that controls "
        "contrast/visibility/layout, and JS that mutates DOM ARIA "
        "attributes. Pure server-side or workflow changes cannot.",
    ),
    (
        "R-009",
        ["seed.py", "app/models/**"],
        "Seed data quality risk: the seed script itself, and the models "
        "whose schema the seed satisfies. A type/constraint change in "
        "models without a matching seed update would surface here.",
    ),
    (
        "R-010",
        [".github/workflows/**"],
        "Image signing is a supply-chain CI concern. Application code "
        "cannot raise this; only the workflow that builds/publishes "
        "container images.",
    ),
    (
        "R-011",
        [
            "app/services/booking_assistant.py",
            "app/templates/member/book_tee_time.html",
            "app/api/schemas.py",
        ],
        "AI feature correctness lives in the assistant service (prompt + "
        "intent schema + slot proposal), the template that renders the "
        "assistant's UI surface, and the API schema for BookingIntentOut.",
    ),
    (
        "R-012",
        ["app/services/booking_assistant.py"],
        "Prompt-injection resistance posture lives where the model's "
        "prompt template and structured-output schema for the assistant "
        "are defined. The API schemas file (app/api/schemas.py) is "
        "deliberately NOT a candidate path — it is contract surface "
        "(R-006), not prompt-injection surface; F-015 named this "
        "distinction explicitly. Any future split that decomposes the "
        "assistant module should be added here.",
    ),
    (
        "R-013",
        [
            "app/__init__.py",
            "app/extensions.py",
        ],
        "Observability emission: prometheus-flask-exporter is initialised "
        "in app/__init__.py and the metric registries live in app/"
        "extensions.py. Application logic changes elsewhere do not affect "
        "what's emitted.",
    ),
    (
        "R-014",
        [".github/workflows/**"],
        "Self-hosted runner SPOF is a workflow-runner-selection concern. "
        "Application code cannot raise this risk.",
    ),
    (
        "R-015",
        [
            "seed.py",
            "tests/fixtures/**",
            "tests/conftest.py",
        ],
        "Fixtures/seed risk: PII would appear in the seed file, in "
        "shared test fixtures, or in fixture-builders configured in "
        "conftest. API contract test data sitting in unit tests is "
        "explicitly NOT in scope (per the row's exclusion clause).",
    ),
    (
        "R-016",
        [".github/workflows/**"],
        "Free-tier minute exhaustion is a workflow-runtime concern. "
        "Application code cannot raise this risk.",
    ),
    (
        "R-017",
        [".github/workflows/**"],
        "Node.js runtime deprecation lives entirely in workflow YAML's "
        "action-version pins and env-var toggles. No application code "
        "can raise this.",
    ),
    (
        "R-018",
        [
            "app/templates/**",
            "app/static/js/**",
            "app/routes/member.py",
            "app/routes/visitor.py",
        ],
        "Functional flake subject: client-side timing on post-click "
        "flows. Templates with form-submit + scroll/redirect, JS that "
        "schedules animations after click, and the route handlers whose "
        "redirect targets are asserted by Playwright. Pure server-side "
        "or AI-prompt changes do not affect the client-side race.",
    ),
    (
        "R-019",
        [".github/workflows/**"],
        "Runner OOM is triggered by changes to the Playwright/a11y job "
        "memory footprint, which is configured in the workflow file. "
        "Application code does not materially shift the runner's memory "
        "boundary.",
    ),
]


def _path_matches(path: str, pattern: str) -> bool:
    """Match a file path against a glob, with `**` meaning any directory depth.

    fnmatch alone treats `*` as any-non-slash, so `app/routes/**` would not
    match `app/routes/member.py`. The `**` extension below splits the
    pattern at its `**` token and requires the path to start with the
    prefix and end with the suffix.
    """
    if "**" in pattern:
        prefix, _, suffix = pattern.partition("**")
        if prefix and not path.startswith(prefix):
            return False
        if suffix and not path.endswith(suffix):
            return False
        return True
    return fnmatch.fnmatch(path, pattern)


def _any_match(path: str, patterns: list[str]) -> bool:
    return any(_path_matches(path, p) for p in patterns)


def candidate_risk_ids(diff: DiffBundle) -> tuple[set[str], bool]:
    """Return (candidate R-IDs, fallback_used).

    For each mapping entry, the R-ID is a candidate if ANY of its patterns
    matches ANY file in the diff. If no entry matches any file, fall back
    to the full register (return every R-ID from the mapping) and report
    fallback_used=True — the caller can surface that the pre-filter saw
    nothing it recognised.
    """
    candidates: set[str] = set()
    for rid, patterns, _ in _MAPPING:
        if any(_any_match(f, patterns) for f in diff.files):
            candidates.add(rid)
    if not candidates:
        return ({rid for rid, _, _ in _MAPPING}, True)
    return (candidates, False)


def candidate_risks(risks: list[Risk], diff: DiffBundle) -> tuple[list[Risk], list[Risk], bool]:
    """Filter the register down to rows the diff can plausibly raise.

    Returns (kept, filtered_out, fallback_used) so callers can surface both
    the agent's input AND what the pre-filter excluded (for human audit).
    Rows not present in the mapping are always passed through — they are
    excluded from the over-pull risk by their absence from `_MAPPING`,
    not by exclusion here.
    """
    ids, fallback_used = candidate_risk_ids(diff)
    mapped_ids = {rid for rid, _, _ in _MAPPING}
    kept: list[Risk] = []
    filtered: list[Risk] = []
    for r in risks:
        if r.id not in mapped_ids:
            # Unmapped row: pass through (we'd rather the agent see it than
            # silently drop it). Practically every row in the live register
            # is mapped; this is defensive.
            kept.append(r)
        elif r.id in ids:
            kept.append(r)
        else:
            filtered.append(r)
    return (kept, filtered, fallback_used)
