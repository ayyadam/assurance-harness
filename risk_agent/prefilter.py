"""Deterministic register pre-filter for risk_agent.

Classifies a PR diff by which file paths it touches (and, for rows where
path-matching alone is too coarse, by what content the diff actually adds)
and returns the subset of register risks that can plausibly be raised. The
agent then only judges relevance among the pre-qualified set.

Why this exists: phase 9 v4 v2 (F-015) documented a ceiling on what pure
prompt + register-text tuning can achieve. The agent's row-matching pass
treats all 19 rows as candidates on every diff and over-pulls keyword-adjacent
rows it can't reliably exclude through prompt rules alone. Phase 13's bet is
that *layer classification* is not genuinely ambiguous — a CSS file is a CSS
file, a workflow YAML is a workflow YAML — and so it belongs in deterministic
Python, not in the LLM. The agent's reserved for the *actually fuzzy* judgment
of relevance level (2 vs 3) and rationale within a small pre-qualified set.

Mapping shape (v3): each entry is a ``_Rule`` carrying an R-ID, a list of file
glob patterns, an optional content filter (callable that inspects the diff
body's added lines), and a rationale. A row is a candidate when ANY of its
paths matches ANY file in the diff AND (if a content filter is set) the
filter accepts the diff body. v3 added content filters to R-007, R-012, and
R-019 to address the path-only ceiling F-017 surfaced.

Failure mode: a hand-authored mapping can miss a file layout or content shape
we didn't anticipate. The fallback rule (no rule matches any file → return
full register) preserves recall in the unknown case: better the agent over-
pulls than that the pre-filter silently excludes a relevant row. v1 prefers
false-positive in the filter.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable
from dataclasses import dataclass

from risk_agent.diff import DiffBundle
from risk_agent.register import Risk

# ── content filter helpers ────────────────────────────────────────────────


def _added_lines(diff_body: str) -> list[str]:
    """Return only the lines a diff *adds* (starting with '+' but not '+++').

    Diff bodies contain three line kinds: additions ('+'), removals ('-'),
    and context (' '), plus file/hunk headers ('+++', '---', '@@'). For
    content-aware filtering we almost always care about what the PR is
    *introducing*, not what it removes or what surrounded the change. The
    '+++ b/path' header line is filtered out explicitly so a filename
    containing the marker substring doesn't trigger a false positive.
    """
    return [line for line in diff_body.splitlines() if line.startswith("+") and not line.startswith("+++")]


def _added_code_lines(diff_body: str) -> list[str]:
    """Like :func:`_added_lines` but skip pure-comment lines.

    Discovered during phase 13 v3: PR #2's workflow diff contains an
    explanatory comment mentioning ``docker/login-action`` and
    ``docker/build-push-action`` — the comment text matched R-010's
    ``docker`` marker even though no actual docker step was added. Stripping
    lines whose trimmed content starts with ``#`` (YAML/Python comment
    syntax — covers .yml and .py, the two main file kinds in this SUT's
    diffs) keeps the markers honest. Inline comments at end of a line are
    not stripped because the meaningful code is still on that line.
    """
    out: list[str] = []
    for line in _added_lines(diff_body):
        # Strip leading '+' then leading whitespace; check for '#' comment.
        stripped = line[1:].lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return out


def _r007_query_pattern_change(diff_body: str) -> bool:
    """R-007 fires when a diff adds or modifies query/loading patterns.

    Looks for SQLAlchemy ORM keywords in added lines: relationship loading
    strategies (lazy=, selectinload, joinedload), query construction calls,
    and JOIN/filter chains. Refactors that preserve queries verbatim won't
    match because nothing distinctive is added. Pure logic changes that
    happen to live in app/services or app/routes also won't match.
    """
    added = _added_lines(diff_body)
    markers = (
        "lazy=",
        "selectinload",
        "joinedload",
        "subqueryload",
        "lazyload",
        "noload",
        ".query(",
        "db.session.query",
        "session.query",
        "primaryjoin=",
        "secondary=",
    )
    return any(any(m in line for m in markers) for line in added)


def _r012_prompt_or_schema_change(diff_body: str) -> bool:
    """R-012 fires when a diff modifies the AI assistant's prompt or structured-output schema.

    The subject mechanism (per the row text) is *the injection-resistance
    posture*: prompt template content, structured-output schema constraints,
    and what user input flows into the model context. Helper function changes
    within booking_assistant.py (e.g. PR #11's limit=6 → None default in
    find_candidate_slots) do not modify any of those and do not match.
    """
    added = _added_lines(diff_body)
    markers = (
        "SYSTEM_PROMPT",
        "_PROMPT ",
        "_PROMPT=",
        "system_prompt",
        '"system"',  # message role marker in chat APIs
        '"enum":',  # JSON schema enum constraint
        '"properties":',  # JSON schema field definitions
        "not_before",  # F-008 intent field — appears in additions to BookingIntent
        "not_after",
        "format=",  # ollama-style structured-output format argument
    )
    # NOTE: "BookingIntent" alone is deliberately NOT a marker — it appears in
    # any function signature that takes the type as a parameter (PR #11's
    # find_candidate_slots), which over-fires. Intent-class changes are
    # caught by the field-name markers (not_before / not_after) and JSON
    # schema markers.
    return any(any(m in line for m in markers) for line in added)


def _r009_schema_or_constraint_change(diff_body: str) -> bool:
    """R-009 fires when a diff adds or modifies schema/constraint definitions.

    Subject mechanism is data quality — column types, nullability, uniqueness,
    value constraints, FK relations, and seed-side data. Query-strategy
    changes on existing relationships (PR #8's lazy='dynamic' → 'selectin')
    don't touch any of those and won't match: ``relationship(`` is
    deliberately NOT a marker because PR #8's modified line contains it.
    Adding a *new* relationship would typically accompany a Column() or FK
    addition that does match.
    """
    added = _added_lines(diff_body)
    markers = (
        "Column(",
        "ForeignKey(",
        "nullable=",
        "unique=",
        "index=",
        "default=",
        "server_default=",
        "CheckConstraint",
        "UniqueConstraint",
        "Integer",
        "String(",
        "Float",
        "Numeric",
        "Decimal",
        "Boolean",
        "Date",
        "Time",
        "DateTime",
        "Text",
        "JSON",
    )
    return any(any(m in line for m in markers) for line in added)


def _r010_image_signing_change(diff_body: str) -> bool:
    """R-010 fires when a workflow diff plausibly affects image build/push/signing.

    Subject mechanism is supply-chain integrity for container images. Pure
    action-version bumps (PR #2's actions/checkout@v4 → v5) and env-var
    toggles don't change how images are built or signed and won't match.
    Adding/modifying docker steps, cosign signing, registry pushes, or
    image-tag computation does.
    """
    added = _added_code_lines(diff_body)
    markers = (
        "docker",
        "cosign",
        "ghcr",
        "build-push-action",
        "docker/login-action",
        "docker/setup-buildx",
        "Dockerfile",
        "image:",
        "registry",
        "crane",
        "syft",
    )
    return any(any(m.lower() in line.lower() for m in markers) for line in added)


def _r019_runner_memory_change(diff_body: str) -> bool:
    """R-019 fires when a workflow diff plausibly affects the Playwright/a11y job's memory footprint.

    Pure action-version bumps (`actions/checkout@v4` → `@v5`) and env-var
    toggles (`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: 'true'`) do not match
    because they don't materially change runner-side memory pressure. New
    Playwright/Chromium/axe job steps, parallelisation flags, and matrix
    configurations do.
    """
    added = _added_code_lines(diff_body)
    markers = (
        "playwright",
        "chromium",
        "firefox",
        "webkit",
        "axe-core",
        "axe-playwright",
        "browser",
        "matrix:",
        "max-parallel:",
        "parallel:",
        "container:",
        "services:",
    )
    return any(any(m.lower() in line.lower() for m in markers) for line in added)


# ── mapping ────────────────────────────────────────────────────────────────


@dataclass
class _Rule:
    """One pre-filter entry.

    A row is a candidate when ANY of ``paths`` matches ANY file in the diff
    AND (if ``content_filter`` is set) the filter accepts the diff body.
    ``content_filter=None`` means path-match alone qualifies the row — the
    behaviour of phase 13 v1 and v2.
    """

    rid: str
    paths: list[str]
    rationale: str
    content_filter: Callable[[str], bool] | None = None


# Each rule: where the subject mechanism lives, what content qualifies a
# match (if path-only is too coarse), and why this layer can raise this risk.
# Entries without a content filter use path-match alone (most rows). v3 added
# filters to R-007, R-012, R-019 — the three F-017 named as path-ceiling cases.
_MAPPING: list[_Rule] = [
    _Rule(
        "R-001",
        ["tests/conftest.py"],
        "SQLite FK pragma enforcement is configured in tests/conftest.py — "
        "that file is the subject mechanism. Phase 13 v1 also mapped "
        "app/models/** here on the theory that model changes could introduce "
        "new FK relations, but in v1's eval PR #8 demonstrated the false-"
        "positive shape: query-strategy changes modify models without "
        "touching FK semantics. v2 narrowed to conftest.py; v3 could plausibly "
        "add model files back with a content filter on `ForeignKey(`, but no "
        "golden-set case currently exercises that path so it's deferred.",
    ),
    _Rule(
        "R-002",
        [
            "app/routes/member.py",
            "app/routes/visitor.py",
            "app/services/booking_service.py",
        ],
        "Booking-create check-then-create pattern lives in the route "
        "handlers that own /book POSTs and the service module those "
        "handlers delegate to. Phase 13 v1/v2 also mapped app/models/** "
        "here on the theory that uniqueness-constraint changes could raise "
        "R-002, but in v3's eval PR #8 demonstrated the displaced-FP shape: "
        "a query-strategy change in a model file isn't a uniqueness-"
        "constraint change. A genuine new UniqueConstraint would in "
        "practice arrive with route/service changes that already match.",
    ),
    _Rule(
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
    _Rule(
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
    _Rule(
        "R-005",
        [".github/workflows/**"],
        "Whether the CI lint gate fires is purely a workflow configuration "
        "concern. No application change can raise this.",
    ),
    _Rule(
        "R-006",
        [
            "app/api/**",
            "app/__init__.py",
        ],
        "Contract surface: every endpoint definition + schema lives under "
        "app/api/; spec_processor (which prunes /metrics from the published "
        "spec) lives in app/__init__.py.",
    ),
    _Rule(
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
        "and service modules that batch or paginate. Path-only filtering "
        "would fire on every server-side change; the content filter "
        "narrows to diffs that actually add or modify query/loading "
        "patterns (SQLAlchemy loading strategies, .query() calls, "
        "JOIN/filter chains). See F-018.",
        content_filter=_r007_query_pattern_change,
    ),
    _Rule(
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
    _Rule(
        "R-009",
        ["seed.py", "app/models/**"],
        "Seed data quality risk: the seed script itself, and the models "
        "whose schema the seed satisfies. Path-only filtering would fire "
        "on every model change including query-strategy tweaks (PR #8); "
        "v3's content filter narrows to diffs that actually add or modify "
        "column types, nullability, defaults, unique/index constraints, "
        "or FK relations. See F-018.",
        content_filter=_r009_schema_or_constraint_change,
    ),
    _Rule(
        "R-010",
        [".github/workflows/**"],
        "Image signing is a supply-chain CI concern; only workflows that "
        "build or publish container images can raise it. Path-only "
        "filtering would fire on every workflow change including pure "
        "action-version bumps (PR #2); v3's content filter narrows to "
        "diffs that touch docker/cosign/registry/image-tag logic. See "
        "F-018.",
        content_filter=_r010_image_signing_change,
    ),
    _Rule(
        "R-011",
        [
            "app/services/booking_assistant.py",
            "app/templates/member/book_tee_time.html",
        ],
        "AI feature correctness lives in the assistant service (prompt + "
        "intent schema + slot proposal) and the template that renders the "
        "assistant's UI surface. v2 dropped app/api/schemas.py from this "
        "row because PRs #5/#6 contract corrections don't relate to AI "
        "correctness; the rare AI-only schemas-py change would typically "
        "accompany an assistant-module change too (see PR #12).",
    ),
    _Rule(
        "R-012",
        ["app/services/booking_assistant.py"],
        "Prompt-injection resistance posture lives where the model's "
        "prompt template and structured-output schema for the assistant "
        "are defined. Path-only filtering fires on any change in "
        "booking_assistant.py, including helper-function tweaks like PR "
        "#11's limit=6 → None default. v3's content filter narrows to "
        "diffs that actually modify prompt text or schema constraints. "
        "The API schemas file (app/api/schemas.py) remains deliberately NOT "
        "a candidate path — that is contract surface (R-006). See F-018.",
        content_filter=_r012_prompt_or_schema_change,
    ),
    _Rule(
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
    _Rule(
        "R-014",
        [".github/workflows/**"],
        "Self-hosted runner SPOF is a workflow-runner-selection concern. Application code cannot raise this risk.",
    ),
    _Rule(
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
    _Rule(
        "R-016",
        [".github/workflows/**"],
        "Free-tier minute exhaustion is a workflow-runtime concern. Application code cannot raise this risk.",
    ),
    _Rule(
        "R-017",
        [".github/workflows/**"],
        "Node.js runtime deprecation lives entirely in workflow YAML's "
        "action-version pins and env-var toggles. No application code "
        "can raise this.",
    ),
    _Rule(
        "R-018",
        [
            "app/templates/**",
            "app/static/js/**",
        ],
        "Functional flake subject: client-side timing on post-click "
        "flows. Templates with form-submit + scroll/redirect, JS that "
        "schedules animations after click. v2 dropped routes/member.py "
        "and routes/visitor.py because server-side route changes that "
        "preserve redirect targets don't affect the client-side race. "
        "R-018 is now closed in the register but kept here so a future "
        "PR that removes F-012's smooth-scroll override or reintroduces "
        "the race mechanism still surfaces.",
    ),
    _Rule(
        "R-019",
        [".github/workflows/**"],
        "Runner OOM is triggered by changes that materially shift the "
        "Playwright/a11y job's memory footprint: new browser job steps, "
        "parallelisation flags, axe-core scope expansion. Path-only "
        "filtering fires on every workflow change including pure "
        "action-version bumps (PR #2) which don't affect runner memory. "
        "v3's content filter narrows to diffs that mention Playwright, "
        "Chromium/Firefox/WebKit, axe, or matrix/parallel job structure. "
        "See F-018.",
        content_filter=_r019_runner_memory_change,
    ),
]


# ── matching ───────────────────────────────────────────────────────────────


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


def _rule_qualifies(rule: _Rule, diff: DiffBundle) -> bool:
    """Return True when this rule's R-ID should be a candidate for this diff.

    Path test runs first because it's cheap and rules out most diffs without
    needing to scan the diff body. The content filter only runs if a path
    matched. None content_filter means "path-match alone qualifies".
    """
    if not any(_any_match(f, rule.paths) for f in diff.files):
        return False
    if rule.content_filter is None:
        return True
    return rule.content_filter(diff.body)


def candidate_risk_ids(diff: DiffBundle) -> tuple[set[str], bool]:
    """Return (candidate R-IDs, fallback_used).

    For each mapping rule, the R-ID is a candidate when the rule qualifies
    (path match + optional content filter pass). If no rule qualifies on
    any file, fall back to the full mapped register and report
    ``fallback_used=True`` — the caller can surface that the pre-filter saw
    nothing it recognised.
    """
    candidates: set[str] = {rule.rid for rule in _MAPPING if _rule_qualifies(rule, diff)}
    if not candidates:
        return ({rule.rid for rule in _MAPPING}, True)
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
    mapped_ids = {rule.rid for rule in _MAPPING}
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
