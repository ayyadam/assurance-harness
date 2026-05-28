"""Access-control journeys at the boundary a real user would hit through the
browser. These map directly to the risk register:

- R-004 (authorization bypass): a logged-in member must not reach admin pages.
- Authentication enforcement: an anonymous visitor must be sent to login
  before any member-only page.
"""

import re

from playwright.sync_api import Page, expect


def test_member_cannot_reach_admin_area(member_page: Page) -> None:
    """A non-admin member is bounced off the admin dashboard (R-004)."""
    page = member_page
    page.goto("/admin/dashboard")

    # admin_required redirects non-admins home with a flash, rather than
    # rendering the admin page.
    expect(page).to_have_url(re.compile(r"localhost:\d+/$"))
    expect(page.locator(".alert")).to_contain_text("Access denied")


def test_anonymous_visitor_is_sent_to_login(page: Page) -> None:
    """An unauthenticated request for a member page redirects to login."""
    page.goto("/member/dashboard")
    expect(page).to_have_url(re.compile(r"/auth/login"))
    expect(page.locator("#member-login")).to_be_visible()
