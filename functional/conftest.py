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
from playwright.sync_api import Page, expect

SUT_BASE_URL = os.getenv("SUT_BASE_URL", "http://localhost:5000")

# Playwright's default expect() assertion timeout is 5s, which is comfortable on
# a developer machine but tight on a cold-container CI runner — the booking-
# confirm POST → DB commit → 302 → GET dashboard chain can spike past 5s under
# load (see F-009 / R-018). 15s gives the cold-runner case headroom without
# masking real regressions; navigation that takes longer than that is a defect,
# not a timing variance.
expect.set_options(timeout=15_000)


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


# CSS smooth-scroll is *non-deterministic in tests*. The booking page's
# slot-selection JS triggers a 50ms-delayed ``scrollIntoView({behavior: 'smooth'})``
# after every slot click. On a fast local machine, that smooth scroll completes
# before the next test action; on a cold CI runner, Playwright's confirm-button
# stability check can race against the smooth scroll and dispatch a click whose
# form-submission side-effect is silently lost in the viewport animation. The
# Playwright trace from PR #25's R-018 hit shows the exact sequence:
# ``performing click action → click action done → navigations have finished``
# (no nav scheduled — the form never POSTed).
#
# Forcing ``scroll-behavior: auto`` on every page returns deterministic scroll.
# Tests still exercise the real submit button, the real form, the real handler —
# only the cosmetic transition is bypassed.
@pytest.fixture
def page(page: Page) -> Page:
    """Override pytest-playwright's page fixture to disable CSS smooth scroll.

    See R-018 / F-009 / F-012 for the full diagnostic trail. The init script
    runs on every navigation in this page's context, so any test that uses
    the `page` fixture (directly or via `member_page`) gets deterministic
    scroll behaviour automatically.
    """
    page.add_init_script("document.documentElement.style.scrollBehavior = 'auto';")
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
