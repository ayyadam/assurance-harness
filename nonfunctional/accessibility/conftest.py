"""Fixtures for accessibility tests against golf-web-app.

These inject axe-core into real browser pages via Playwright and require the
SUT running and reachable at SUT_BASE_URL (default http://localhost:5000):

    cd ../golf-web-app
    docker compose up -d
    docker compose exec web python seed.py

Then, from this repo:

    uv run playwright install chromium   # one-time browser download
    uv run pytest nonfunctional/accessibility/

Accessibility tests are excluded from the default `pytest` run (which targets
tests/ and needs no SUT). Run them explicitly as above.
"""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from playwright.sync_api import Page

SUT_BASE_URL = os.getenv("SUT_BASE_URL", "http://localhost:5000")

# Where per-page axe JSON results are written for evidence / CI artifacts.
# Nonfunctional layers own their evidence dir, matching ai_evaluation/ and risk_agent/.
REPORT_DIR = Path(__file__).resolve().parent.parent / "reports" / "a11y"


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str


@pytest.fixture(scope="session")
def base_url() -> str:
    """Override pytest-base-url's fixture so relative page.goto() resolves."""
    return SUT_BASE_URL


@pytest.fixture(scope="session")
def report_dir() -> Path:
    """Directory for axe result artifacts; created once per session."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return REPORT_DIR


@pytest.fixture(scope="session")
def member() -> Credentials:
    """A seeded non-admin member (see golf-web-app/seed.py)."""
    return Credentials(
        username=os.getenv("SUT_USERNAME", "john.smith"),
        password=os.getenv("SUT_PASSWORD", "Password1"),
    )


@pytest.fixture
def login() -> Callable[[Page, str, str], None]:
    """Return a helper that signs in through the real login form."""

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
