"""Tests for the risk_agent register pre-filter (phase 13 v1).

The pre-filter is deterministic Python — that's the *point* of moving layer
classification out of the LLM. Deterministic = testable: these tests assert
that each historical golden-set PR shape filters to the candidate set we
expect, and that the no-match fallback preserves recall.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from risk_agent.prefilter import candidate_risk_ids, candidate_risks
from risk_agent.register import Risk


@dataclass
class _StubDiff:
    """Minimal stand-in for DiffBundle — only ``files`` is read by the pre-filter."""

    files: list[str]


def _risks(*ids: str) -> list[Risk]:
    """Build a thin Risk list with only `id` set — the rest isn't read here."""
    return [Risk(id=rid, description="", likelihood="", impact="", score="", status="", mitigation="") for rid in ids]


# ── per-layer expectations ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "diff_files,must_include,must_exclude",
    [
        # PR #2 shape: workflow-only bump
        (
            [".github/workflows/ci-cd.yml"],
            {"R-005", "R-010", "R-014", "R-016", "R-017", "R-019"},
            {"R-002", "R-006", "R-008", "R-011", "R-012", "R-013"},
        ),
        # PR #3 shape: booking-service refactor — touches routes + service + models.
        # The deliberate v3/v4 v2 stress test for R-002.
        (
            ["app/routes/member.py", "app/routes/visitor.py", "app/services/booking_service.py"],
            {"R-002", "R-007", "R-018"},
            {"R-005", "R-008", "R-010", "R-014", "R-017", "R-019"},
        ),
        # PR #7 shape: a11y CSS + DOM-mutating JS only
        (
            ["app/static/css/style.css", "app/static/js/main.js"],
            {"R-008", "R-018"},
            {"R-002", "R-005", "R-006", "R-010", "R-014", "R-017"},
        ),
        # PR #12 shape: AI feature schema + template + assistant
        (
            [
                "app/api/schemas.py",
                "app/services/booking_assistant.py",
                "app/templates/member/book_tee_time.html",
            ],
            {"R-006", "R-008", "R-011", "R-012", "R-018"},
            {"R-005", "R-010", "R-014", "R-017", "R-019"},
        ),
        # PR #14 shape: spec_processor in __init__.py + a unit test
        (
            ["app/__init__.py"],
            {"R-006", "R-013"},
            {"R-002", "R-005", "R-008", "R-010", "R-014", "R-017"},
        ),
        # PR #8 shape: model query strategy change (lazy='dynamic' → 'selectin').
        # Regression guard: the project uses `app/models/` as a directory, not
        # a single `app/models.py` file. Without the `app/models/**` pattern,
        # PR #8 hits the fallback (full register) and R-017 gets over-pulled.
        (
            ["app/models/booking.py"],
            {"R-001", "R-002", "R-007", "R-009"},
            {"R-005", "R-008", "R-010", "R-014", "R-017", "R-019"},
        ),
    ],
)
def test_candidate_risk_ids_per_layer(diff_files: list[str], must_include: set[str], must_exclude: set[str]) -> None:
    """For each historical PR shape, assert the candidate set's membership.

    `must_include` are R-IDs the pre-filter MUST classify as candidates for
    this diff shape; `must_exclude` are R-IDs the pre-filter MUST NOT include.
    Other R-IDs (not in either set) are unconstrained — the test asserts the
    bits that matter for v1, not the entire mapping.
    """
    diff = _StubDiff(files=diff_files)
    ids, fallback_used = candidate_risk_ids(diff)
    assert not fallback_used, f"unexpected fallback for {diff_files}"
    missing = must_include - ids
    leaked = must_exclude & ids
    assert not missing, f"pre-filter missed required candidates: {missing}"
    assert not leaked, f"pre-filter leaked excluded candidates: {leaked}"


# ── fallback ──────────────────────────────────────────────────────────────


def test_fallback_when_no_pattern_matches_returns_full_register() -> None:
    """No file in the diff matches any mapped pattern → full register.

    This is the v1 recall preservation: better to send everything than
    silently exclude a row. The agent might over-pull but the reviewer
    still sees every candidate.
    """
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
    assert "R-017" in kept_ids and "R-019" in kept_ids, "workflow-mapped rows should be kept"
    assert "R-002" in filtered_ids and "R-006" in filtered_ids and "R-008" in filtered_ids, (
        "feature/contract/UI rows should be filtered out for a workflow-only diff"
    )
    assert kept_ids.isdisjoint(filtered_ids), "kept and filtered partitions must not overlap"


def test_unmapped_risk_id_passes_through() -> None:
    """A Risk whose ID isn't in the mapping is passed through (defensive)."""
    diff = _StubDiff(files=[".github/workflows/ci-cd.yml"])
    risks = _risks("R-999")  # not in the mapping
    kept, filtered, _ = candidate_risks(risks, diff)
    assert any(r.id == "R-999" for r in kept), "unmapped risks must pass through, not silently drop"
    assert not any(r.id == "R-999" for r in filtered)
