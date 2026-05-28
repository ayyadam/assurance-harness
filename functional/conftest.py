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
