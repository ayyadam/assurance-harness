"""F-028 — the UI agent's page snapshot perceives non-interactive clickables.

Hermetic Playwright test (no SUT, no LLM, no seed dependency): load a known DOM
snippet via ``set_content`` and assert ``_snapshot_interactive`` captures BOTH
standard form controls AND ``<div onclick>`` / ``role="button"`` clickables — the
way the booking assistant renders its result slots (`<div class="booking-slot"
onclick=…>`). Before F-028 the snapshot queried only ``a, button, input,
textarea, select``, so those result slots were invisible and the booking tour
could not perceive that suggestions had arrived (it exhausted its step budget).

This guards the widening: if the selector is ever narrowed back, the booking-slot
assertions go red. It runs in the Functional (Playwright) CI job; it needs no SUT
navigation, so it is immune to seed-window/availability drift.
"""

from __future__ import annotations

from explore_agent.ui_probe import _snapshot_interactive

_HTML = """
<!doctype html><html><body>
  <a id="home" href="/">Home</a>
  <button id="go">Go</button>
  <input id="q" placeholder="search">
  <div class="booking-slot" onclick="selectTeeTime(1, this)">07:00</div>
  <div class="booking-slot" onclick="selectTeeTime(2, this)">07:10</div>
  <span role="button" class="chip">Pick</span>
  <p>just text, not interactive</p>
</body></html>
"""


def test_snapshot_perceives_onclick_and_role_clickables(page) -> None:
    page.set_content(_HTML)
    rows = _snapshot_interactive(page)

    # Standard controls are still captured (no regression).
    assert any(r.startswith("a#home") for r in rows), rows
    assert any(r.startswith("button#go") for r in rows), rows
    assert any(r.startswith("input#q") for r in rows), rows

    # F-028: non-interactive clickables are now captured, with a usable selector hint.
    slot_rows = [r for r in rows if "div.booking-slot" in r]
    assert len(slot_rows) == 2, f"expected 2 booking-slot rows, got: {rows}"
    assert any("07:00" in r for r in slot_rows), slot_rows
    # role="button" on a non-standard tag is captured too.
    assert any(r.startswith("span.chip") for r in rows), rows

    # A genuinely non-interactive element is NOT captured.
    assert not any(r.startswith("p ") or r == 'p ""' for r in rows), rows
