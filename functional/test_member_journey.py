"""The core authenticated journeys: a member signs in, books a tee time
through the real browser flow, and signs out.

This is the headline end-to-end evidence for the functional layer — it
exercises the booking path exactly as a member would, including the
JavaScript slot selection and the CSRF-protected form submission.
"""

import re
from collections.abc import Callable
from datetime import date, timedelta

from playwright.sync_api import Page, expect


def test_member_login_succeeds(page: Page, login: Callable[[Page, str, str], None], member) -> None:
    login(page, member.username, member.password)
    expect(page).to_have_url(re.compile(r"/member/dashboard"))
    expect(page.locator("#member-dashboard")).to_be_visible()
    expect(page.locator(".alert")).to_contain_text(f"Welcome back, {member.first_name}")


def test_member_login_rejects_bad_password(page: Page, login: Callable[[Page, str, str], None], member) -> None:
    login(page, member.username, "definitely-wrong")
    # No redirect: the login page re-renders with an error and no session.
    expect(page.locator("#member-login")).to_be_visible()
    expect(page.locator(".alert")).to_contain_text("Invalid username or password")


def test_member_books_a_tee_time(member_page: Page) -> None:
    page = member_page

    # Book two days out so a full slate of slots exists regardless of the
    # time of day the suite runs.
    booking_date = (date.today() + timedelta(days=2)).isoformat()
    page.goto(f"/member/book-tee-time?date={booking_date}")

    # Bookable slots are plain .booking-slot; full/already-booked ones carry
    # the "booked" class and have no click handler.
    slot = page.locator(".booking-slot:not(.booked)").first
    expect(slot).to_be_visible()
    slot.click()

    confirm = page.locator("#confirmBookingBtn")
    expect(confirm).to_be_visible()
    confirm.click()

    expect(page).to_have_url(re.compile(r"/member/dashboard"))
    expect(page.locator(".alert")).to_contain_text("Tee time booked successfully")


def test_member_can_log_out(member_page: Page) -> None:
    page = member_page
    page.click("#user-link")  # open the user dropdown in the navbar
    page.click("#logout-link")

    expect(page).to_have_url(re.compile(r"localhost:\d+/$"))
    expect(page.locator(".alert")).to_contain_text("You have been logged out")
    expect(page.locator("#member-login-link")).to_be_visible()
