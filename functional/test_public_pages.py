"""Public-facing smoke journeys: the site is reachable and the top-level
navigation renders real pages (not error pages).

These are deliberately lightweight — they prove the app is alive and serving
HTML before the heavier authenticated journeys run.
"""

import re

from playwright.sync_api import Page, expect


def test_home_page_loads(page: Page) -> None:
    page.goto("/")
    expect(page).to_have_title(re.compile(r"Adam's Golf Club"))
    expect(page.locator("#adams-golf-club")).to_be_visible()
    expect(page.locator("#member-login-link")).to_be_visible()


def test_top_nav_reaches_public_pages(page: Page) -> None:
    """Click through the primary nav and confirm each destination renders.

    The brand element lives in the shared layout, so its presence after each
    click is a cheap signal that a real page rendered rather than a 500.
    """
    page.goto("/")

    page.click("#course-overview-link")
    expect(page).to_have_url(re.compile(r"/course$"))
    expect(page.locator("#adams-golf-club")).to_be_visible()

    page.click("#scorecard-link")
    expect(page).to_have_url(re.compile(r"/course/scorecard$"))
    expect(page.locator("#adams-golf-club")).to_be_visible()

    page.click("#membership-link")
    expect(page).to_have_url(re.compile(r"/membership$"))
    expect(page.locator("#adams-golf-club")).to_be_visible()
