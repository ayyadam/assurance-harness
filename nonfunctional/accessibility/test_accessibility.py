"""Accessibility sweep of golf-web-app's key pages using axe-core.

Scope and budget (risk-based, not exhaustive):

- We scan the highest-value pages a real user passes through, public and
  authenticated, rather than every route.
- We run the WCAG 2.1 A/AA rule tags — the level most organisations commit to.
- We gate the build on *critical* and *serious* violations (the ones that
  genuinely block users). *minor* and *moderate* issues are still captured in
  the saved JSON report for tracking, but do not fail the PR.

Full axe results for every page are written to reports/a11y/ as evidence.
"""

from pathlib import Path

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page

# Impacts that fail the build. Tracked-but-non-blocking: minor, moderate.
BLOCKING_IMPACTS = {"critical", "serious"}

# Limit axe to the WCAG 2.1 A/AA success criteria — a defensible, standard
# conformance target rather than every best-practice rule axe ships.
AXE_OPTIONS = {
    "runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]},
}

PUBLIC_PAGES = [
    ("home", "/"),
    ("login", "/auth/login"),
    ("membership", "/membership"),
    ("course", "/course"),
]

MEMBER_PAGES = [
    ("member-dashboard", "/member/dashboard"),
    ("book-tee-time", "/member/book-tee-time"),
]

_axe = Axe()


def _scan(page: Page, name: str, report_dir: Path) -> list[dict]:
    """Run axe on the current page, save full results, return blocking violations."""
    results = _axe.run(page, options=AXE_OPTIONS)
    results.save_to_file(report_dir / f"{name}.json", violations_only=True)
    return [v for v in results.response["violations"] if v["impact"] in BLOCKING_IMPACTS]


def _summarise(blocking: list[dict]) -> str:
    return "\n".join(
        f"  [{v['impact']}] {v['id']}: {v['help']} ({len(v['nodes'])} node(s)) -> {v['helpUrl']}" for v in blocking
    )


@pytest.mark.parametrize(("name", "path"), PUBLIC_PAGES, ids=[n for n, _ in PUBLIC_PAGES])
def test_public_page_has_no_blocking_a11y_violations(page: Page, report_dir: Path, name: str, path: str) -> None:
    page.goto(path)
    blocking = _scan(page, name, report_dir)
    assert not blocking, f"{name} ({path}) has blocking WCAG A/AA violations:\n{_summarise(blocking)}"


@pytest.mark.parametrize(("name", "path"), MEMBER_PAGES, ids=[n for n, _ in MEMBER_PAGES])
def test_member_page_has_no_blocking_a11y_violations(member_page: Page, report_dir: Path, name: str, path: str) -> None:
    member_page.goto(path)
    blocking = _scan(member_page, name, report_dir)
    assert not blocking, f"{name} ({path}) has blocking WCAG A/AA violations:\n{_summarise(blocking)}"
