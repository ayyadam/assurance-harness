"""Fixtures for functional (browser) tests against golf-web-app.

These drive a real browser via Playwright and require the SUT running and
reachable at SUT_BASE_URL (default http://localhost:5000). Bring it up first:

    cd ../golf-web-app
    docker compose up -d
    docker compose exec web python seed.py

Then, from this repo:

    uv run playwright install chromium   # one-time browser download
    uv run pytest functional/

Functional tests are intentionally excluded from the default `pytest` run
(which targets tests/ and needs no SUT). Run them explicitly as above.
"""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from playwright.sync_api import Page

SUT_BASE_URL = os.getenv("SUT_BASE_URL", "http://localhost:5000")

# R-018 — intermittent booking-confirm flake on cold CI runners. History:
# F-009 bumped the global expect() timeout to 15s (wrong problem; reverted).
# F-012 traced it to a client-side smooth-scroll race and disabled CSS
# scroll-behavior (below); R-018 was closed after 5 clean runs. F-025 RE-OPENED
# it: the closure was false confidence from an intermittent absence, and the CI
# trace from the recurrence proved F-012's CSS-only fix never disabled the
# actual animation — the booking page calls scrollIntoView({behavior:'smooth'})
# with an EXPLICIT behavior argument, which per CSSOM overrides the CSS
# scroll-behavior property. The effective fix is the scrollIntoView shim in the
# page fixture below. See F-025 in test-strategy.md.


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str
    first_name: str


@pytest.fixture(scope="session")
def base_url() -> str:
    """Override pytest-base-url's fixture so relative page.goto() resolves.

    pytest-playwright passes this into the browser context, so tests can use
    paths like page.goto("/auth/login") instead of hard-coding the host.
    """
    return SUT_BASE_URL


# Smooth scrolling is *non-deterministic in tests*. The booking page's
# slot-selection JS runs ``scrollIntoView({behavior: 'smooth'})`` on the wrapper
# that contains the confirm submit button. On a cold CI runner, Playwright's
# confirm-button click races the animation and the click is lost — the form
# never POSTs (proven by the F-025 trace: the failed run shows login → dashboard
# → booking-page loads in ms, then NO booking POST at all, then a 30s nav
# timeout). We neutralise the animation in two layers, because they cover
# different code paths:
#
#   1. ``scroll-behavior: auto`` on the root — kills CSS-driven smooth scroll.
#   2. a ``scrollIntoView`` shim coercing every call to ``behavior: 'auto'`` —
#      kills calls that pass ``behavior: 'smooth'`` EXPLICITLY. The CSS property
#      does NOT override an explicit argument (CSSOM), which is why F-012's
#      layer-1-only fix never disabled the booking page's animation. F-025.
#
# Tests still exercise the real submit button, form, and handler; only the
# cosmetic transition is bypassed.
@pytest.fixture
def page(page: Page) -> Page:
    """Override pytest-playwright's page fixture to make scrolling deterministic.

    See R-018 / F-012 / F-025 for the full diagnostic trail. The init script
    runs on every navigation in this page's context, so any test that uses the
    `page` fixture (directly or via `member_page`) is covered automatically.
    """
    page.add_init_script(
        "document.documentElement.style.scrollBehavior = 'auto';"
        "(() => {"
        "  const orig = Element.prototype.scrollIntoView;"
        "  Element.prototype.scrollIntoView = function (arg) {"
        "    if (arg && typeof arg === 'object') {"
        "      return orig.call(this, Object.assign({}, arg, { behavior: 'auto' }));"
        "    }"
        "    return orig.call(this, arg);"
        "  };"
        "})();"
    )
    return page


@pytest.fixture(scope="session")
def member() -> Credentials:
    """A seeded non-admin member (see golf-web-app/seed.py)."""
    return Credentials(
        username=os.getenv("SUT_USERNAME", "john.smith"),
        password=os.getenv("SUT_PASSWORD", "Password1"),
        first_name="John",
    )


@pytest.fixture
def login() -> Callable[[Page, str, str], None]:
    """Return a helper that signs in through the real login form.

    The browser submits the form's hidden CSRF token, so this exercises the
    same path a member uses — no API shortcut.
    """

    def _login(page: Page, username: str, password: str) -> None:
        page.goto("/auth/login")
        page.fill("#username", username)
        page.fill("#password", password)
        page.click("#sign-in-button")

    return _login


@pytest.fixture
def member_page(page: Page, login: Callable[[Page, str, str], None], member: Credentials) -> Page:
    """A page already authenticated as a seeded non-admin member."""
    login(page, member.username, member.password)
    page.wait_for_url(re.compile(r"/member/dashboard"))
    return page
