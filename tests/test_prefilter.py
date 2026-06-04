"""Tests for the risk_agent register pre-filter (phase 13 v1 / v2 / v3).

The pre-filter is deterministic Python — that's the *point* of moving layer
classification out of the LLM. Deterministic = testable. These tests cover:

- v1 / v2: per-layer expectations on path-only rules (the original 6 PR
  shapes from the golden set) and the fallback / partition contract.
- v3: per-rule positive/negative tests for the content filters added to
  R-007 (query patterns), R-012 (prompt + schema markers), and R-019
  (memory-relevant workflow changes). The same per-layer tests rely on
  *empty diff bodies* in the stub, which means content-filtered rows
  correctly drop out of those assertions — the stubs deliberately test
  the path-only behaviour and the content-filter tests stand alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from risk_agent.prefilter import candidate_risk_ids, candidate_risks
from risk_agent.register import Risk


@dataclass
class _StubDiff:
    """Minimal stand-in for DiffBundle — only ``files`` and ``body`` are read."""

    files: list[str]
    body: str = field(default="")


def _risks(*ids: str) -> list[Risk]:
    """Build a thin Risk list with only `id` set — the rest isn't read here."""
    return [Risk(id=rid, description="", likelihood="", impact="", score="", status="", mitigation="") for rid in ids]


# ── per-layer expectations (path-only behaviour with empty stub body) ─────


@pytest.mark.parametrize(
    "diff_files,must_include,must_exclude",
    [
        # PR #2 shape: workflow-only bump. Empty stub body → R-019's
        # content filter doesn't fire (no Playwright/Chromium/axe markers).
        # That's the correct path-only assertion; R-019's positive case
        # is covered separately in the content-filter tests below.
        (
            [".github/workflows/ci-cd.yml"],
            {"R-005", "R-010", "R-014", "R-016", "R-017"},
            {"R-002", "R-006", "R-008", "R-011", "R-012", "R-013", "R-019"},
        ),
        # PR #3 shape: booking-service refactor — touches routes + service + models.
        # The deliberate v3/v4 v2 stress test for R-002.
        # v3: R-007 has a content filter (query patterns); with empty body
        # R-007 doesn't fire here, which matches the v3 win on PR #3.
        (
            ["app/routes/member.py", "app/routes/visitor.py", "app/services/booking_service.py"],
            {"R-002"},
            {"R-005", "R-007", "R-008", "R-010", "R-014", "R-017", "R-018", "R-019"},
        ),
        # PR #7 shape: a11y CSS + DOM-mutating JS only. No content-filtered
        # rules apply at these paths so v3 behaves identically to v2.
        (
            ["app/static/css/style.css", "app/static/js/main.js"],
            {"R-008", "R-018"},
            {"R-002", "R-005", "R-006", "R-010", "R-014", "R-017"},
        ),
        # PR #12 shape: AI feature schema + template + assistant.
        # v3: R-012 has a content filter; with empty body R-012 doesn't
        # fire on the per-layer stub. Real PR #12 diff content does fire
        # R-012 (covered in the content-filter tests below).
        (
            [
                "app/api/schemas.py",
                "app/services/booking_assistant.py",
                "app/templates/member/book_tee_time.html",
            ],
            {"R-006", "R-008", "R-011", "R-018"},
            {"R-005", "R-010", "R-012", "R-014", "R-017", "R-019"},
        ),
        # PR #14 shape: spec_processor in __init__.py + a unit test.
        # No content-filtered rules apply at this path.
        (
            ["app/__init__.py"],
            {"R-006", "R-013"},
            {"R-002", "R-005", "R-008", "R-010", "R-014", "R-017"},
        ),
        # PR #8 shape: model file under app/models/ directory.
        # v3: R-007 doesn't fire on empty body (real PR #8 diff content
        # adds `lazy=` and so DOES fire R-007 — covered separately).
        (
            ["app/models/booking.py"],
            {"R-002", "R-009"},
            {"R-001", "R-005", "R-007", "R-008", "R-010", "R-014", "R-017", "R-019"},
        ),
        # PR #5 / #6 shape: API schema-only changes (contract corrections,
        # input security). Regression guard for the v2 R-011 narrowing.
        (
            ["app/api/schemas.py", "app/api/views.py"],
            {"R-003", "R-006"},
            {"R-005", "R-008", "R-010", "R-011", "R-014", "R-017", "R-018", "R-019"},
        ),
        # Template-only diff — regression guard for the v2 R-018 narrowing.
        (
            ["app/templates/member/book_tee_time.html"],
            {"R-008", "R-011", "R-018"},
            {"R-002", "R-005", "R-010", "R-014", "R-017", "R-019"},
        ),
    ],
)
def test_candidate_risk_ids_per_layer(diff_files: list[str], must_include: set[str], must_exclude: set[str]) -> None:
    """For each historical PR shape, assert the candidate set's membership."""
    diff = _StubDiff(files=diff_files)
    ids, fallback_used = candidate_risk_ids(diff)
    assert not fallback_used, f"unexpected fallback for {diff_files}"
    missing = must_include - ids
    leaked = must_exclude & ids
    assert not missing, f"pre-filter missed required candidates: {missing}"
    assert not leaked, f"pre-filter leaked excluded candidates: {leaked}"


# ── v3 content filters: R-007, R-012, R-019 positive + negative ────────────


def test_r007_fires_on_lazy_loading_strategy_change() -> None:
    """The PR #8 shape: ``lazy='dynamic' → 'selectin'`` SHOULD raise R-007."""
    diff = _StubDiff(
        files=["app/models/booking.py"],
        body=(
            "@@ -10,7 +10,7 @@\n"
            "-    bookings = relationship('Booking', lazy='dynamic')\n"
            "+    bookings = relationship('Booking', lazy='selectin')\n"
        ),
    )
    ids, _ = candidate_risk_ids(diff)
    assert "R-007" in ids


def test_r007_skips_pure_logic_refactor() -> None:
    """A server-side diff that doesn't touch query patterns must NOT raise R-007."""
    diff = _StubDiff(
        files=["app/services/booking_service.py"],
        body="@@ -10,5 +10,5 @@\n-def old_helper():\n+def new_helper():\n     return 42\n",
    )
    ids, _ = candidate_risk_ids(diff)
    assert "R-007" not in ids


def test_r012_fires_on_prompt_template_change() -> None:
    """A diff that adds SYSTEM_PROMPT lines SHOULD raise R-012."""
    diff = _StubDiff(
        files=["app/services/booking_assistant.py"],
        body='@@ -1,3 +1,5 @@\n+SYSTEM_PROMPT = """You are a booking assistant..."""\n+\n def make_call(): pass\n',
    )
    ids, _ = candidate_risk_ids(diff)
    assert "R-012" in ids


def test_r012_fires_on_intent_schema_field_addition() -> None:
    """A diff that adds intent schema fields (the F-008 shape) SHOULD raise R-012."""
    diff = _StubDiff(
        files=["app/services/booking_assistant.py"],
        body=(
            "@@ -10,2 +10,4 @@\n"
            "     class BookingIntent:\n"
            "+        not_before: time | None = None\n"
            "+        not_after: time | None = None\n"
        ),
    )
    ids, _ = candidate_risk_ids(diff)
    assert "R-012" in ids


def test_r012_skips_helper_function_change() -> None:
    """The PR #11 shape: ``limit=6 → None`` default in a helper must NOT raise R-012."""
    diff = _StubDiff(
        files=["app/services/booking_assistant.py"],
        body=(
            "@@ -42,7 +42,15 @@\n"
            "-def find_candidate_slots(intent, slots, limit=6):\n"
            "+def find_candidate_slots(intent, slots, limit=None):\n"
        ),
    )
    ids, _ = candidate_risk_ids(diff)
    assert "R-012" not in ids


def test_r019_fires_on_playwright_step_addition() -> None:
    """A workflow diff that adds Playwright steps SHOULD raise R-019."""
    diff = _StubDiff(
        files=[".github/workflows/ci-cd.yml"],
        body="@@ -50,4 +50,8 @@\n+      - name: Run Playwright tests\n+        run: npx playwright test\n",
    )
    ids, _ = candidate_risk_ids(diff)
    assert "R-019" in ids


def test_r019_skips_pure_action_version_bump() -> None:
    """The PR #2 shape: ``actions/checkout@v4 → v5`` must NOT raise R-019."""
    diff = _StubDiff(
        files=[".github/workflows/ci-cd.yml"],
        body="@@ -10,2 +10,2 @@\n-      - uses: actions/checkout@v4\n+      - uses: actions/checkout@v5\n",
    )
    ids, _ = candidate_risk_ids(diff)
    assert "R-019" not in ids


# ── fallback + partition contract ──────────────────────────────────────────


def test_fallback_when_no_pattern_matches_returns_full_register() -> None:
    """No file in the diff matches any mapped pattern → full register."""
    diff = _StubDiff(files=["docs/some-untracked-folder/notes.md"])
    ids, fallback_used = candidate_risk_ids(diff)
    assert fallback_used is True
    assert "R-002" in ids and "R-017" in ids, "fallback should expose all mapped risks"


def test_candidate_risks_partitions_input_kept_and_filtered() -> None:
    """candidate_risks() returns (kept, filtered_out, fallback_used) consistent with the IDs."""
    diff = _StubDiff(files=[".github/workflows/ci-cd.yml"])
    risks = _risks("R-002", "R-006", "R-008", "R-017", "R-019")
    kept, filtered, fallback_used = candidate_risks(risks, diff)
    assert fallback_used is False
    kept_ids = {r.id for r in kept}
    filtered_ids = {r.id for r in filtered}
    assert "R-017" in kept_ids, "workflow-mapped path-only rows should be kept"
    assert "R-002" in filtered_ids and "R-006" in filtered_ids and "R-008" in filtered_ids, (
        "feature/contract/UI rows should be filtered out for a workflow-only diff"
    )
    # R-019 has a content filter; with an empty body the content filter
    # excludes it, so a workflow-only diff with no Playwright markers
    # filters R-019 out. That's the v3 fix for PR #2's over-pull.
    assert "R-019" in filtered_ids, "R-019 should be content-filtered out for a pure-version-bump workflow diff"
    assert kept_ids.isdisjoint(filtered_ids), "kept and filtered partitions must not overlap"


def test_unmapped_risk_id_passes_through() -> None:
    """A Risk whose ID isn't in the mapping is passed through (defensive)."""
    diff = _StubDiff(files=[".github/workflows/ci-cd.yml"])
    risks = _risks("R-999")  # not in the mapping
    kept, filtered, _ = candidate_risks(risks, diff)
    assert any(r.id == "R-999" for r in kept), "unmapped risks must pass through, not silently drop"
    assert not any(r.id == "R-999" for r in filtered)
