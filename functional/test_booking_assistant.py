"""Functional coverage of the natural-language booking assistant UI.

This is the deterministic gate: it runs against the SUT's stub extractor (the
default when no model is configured), so the assertions are stable. It proves
the end-to-end plumbing — type a request, see the interpretation and matching
slots, pick one, and complete the booking through the normal confirm flow.

Semantic quality of a real model's interpretation is non-deterministic and is
assessed in the phase-8 evaluation harness, not here.
"""

import re

from playwright.sync_api import Page, expect


def test_assistant_interprets_request_and_books_a_slot(member_page: Page) -> None:
    page = member_page
    page.goto("/member/book-tee-time")

    page.fill("#assist_text", "a two-ball tomorrow morning")
    page.click("#assist-button")

    # The interpretation is shown back to the member (transparency: they can
    # see what was understood and correct it if needed).
    interpretation = page.locator("#assistant-interpretation")
    expect(interpretation).to_be_visible()
    expect(interpretation).to_contain_text("2")
    expect(interpretation).to_contain_text("morning")

    # Proposed candidate slots render as normal bookable slots.
    slot = page.locator(".booking-slot:not(.booked)").first
    expect(slot).to_be_visible()
    slot.click()

    confirm = page.locator("#confirmBookingBtn")
    expect(confirm).to_be_visible()
    confirm.click()

    # The booking completes through the existing deterministic flow.
    expect(page).to_have_url(re.compile(r"/member/dashboard"))
    expect(page.locator(".alert")).to_contain_text("Tee time booked successfully")
