"""Predefined tour goals for UI-level exploration.

v1 v2 defines three fixed tours covering distinct surfaces of the SUT. The
list is intentionally small — the value here is depth of judgement per step,
not breadth of coverage. The functional layer already exercises the
deterministic journeys; the exploratory agent adds adversarial LLM-driven
interpretation on top of the same surface.

Adding a new tour: append a ``TourGoal`` here. No CLI changes needed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TourGoal:
    name: str  # kebab-case id used in reports and CLI selection
    description: str  # one-line goal handed to the LLM planner
    starting_url: str  # relative to base_url; executor navigates here before planning
    requires_auth: bool  # if True, executor pre-logs in via deterministic UI form before planning
    max_steps: int  # hard cap on plan length to bound runtime


TOURS: list[TourGoal] = [
    TourGoal(
        name="public-pages",
        description=(
            "Browse the public marketing surface of the golf club site. The visitor is not "
            "logged in. From the homepage, navigate to at least two other public pages "
            "(course overview, scorecard, membership, contact) to verify they load cleanly "
            "and the navigation links resolve. Stay logged out throughout."
        ),
        starting_url="/",
        requires_auth=False,
        max_steps=6,
    ),
    TourGoal(
        name="member-login-dashboard",
        description=(
            "A returning member arrives at the login page and signs in to reach the member "
            "dashboard. Fill in the username and password fields with the supplied seed "
            "credentials, submit the form, and verify the dashboard renders without errors. "
            "Do not log out."
        ),
        starting_url="/auth/login",
        requires_auth=False,  # login IS the goal of this tour, do not pre-auth
        max_steps=5,
    ),
    TourGoal(
        name="booking-assistant",
        description=(
            "A logged-in member uses the natural-language booking assistant on the booking "
            "page. Type a free-text request such as 'a 4-ball tomorrow morning' into the "
            "assistant input and submit. Verify the assistant returns plausible candidate "
            "slots. STOP at the suggestion phase — do not click a slot to confirm a booking "
            "(state mutation is out of scope for v1)."
        ),
        starting_url="/member/book-tee-time",
        requires_auth=True,
        max_steps=5,
    ),
]


def get_tour(name: str) -> TourGoal:
    for t in TOURS:
        if t.name == name:
            return t
    available = ", ".join(t.name for t in TOURS)
    raise KeyError(f"unknown tour {name!r}. available: {available}")
