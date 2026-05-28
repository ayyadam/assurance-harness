"""Data-quality checks on golf-web-app's persisted data.

Two layers of assurance per table:

- a pandera schema for column *contracts* — types, nullability, uniqueness,
  allowed value sets, plausible ranges; and
- explicit *business-rule invariants* that span the table — e.g. a course is
  exactly 18 holes whose stroke indexes form a 1..18 permutation.

Scope is risk-based: the four tables carrying real business meaning, not every
table. Validation runs against the live SUT database (see conftest).
"""

from datetime import date, timedelta

import pandas as pd
from pandera.pandas import Check, Column, DataFrameSchema

MEMBERSHIP_TYPES = ["Full Year", "6 Month"]
COMPETITION_FORMATS = ["Stableford", "Medal", "Matchplay", "Texas Scramble", "Fourball"]

members_schema = DataFrameSchema(
    {
        "username": Column(str, nullable=False, unique=True),
        "email": Column(str, Check.str_matches(r".+@.+\..+"), nullable=False, unique=True),
        "first_name": Column(str, nullable=False),
        "last_name": Column(str, nullable=False),
        "telephone": Column(str, nullable=False),
        "membership_type": Column(str, Check.isin(MEMBERSHIP_TYPES), nullable=False),
        "handicap": Column(float, Check.in_range(-10.0, 54.0), nullable=True, coerce=True),
        "is_admin": Column(bool, nullable=False),
        "is_active": Column(bool, nullable=False),
    },
    strict=False,
)

tee_times_schema = DataFrameSchema(
    {
        "max_players": Column(int, Check.gt(0), nullable=False),
        "is_available": Column(bool, nullable=False),
    },
    strict=False,
)

competitions_schema = DataFrameSchema(
    {
        "name": Column(str, nullable=False),
        "format": Column(str, Check.isin(COMPETITION_FORMATS), nullable=False),
        "is_active": Column(bool, nullable=False),
    },
    strict=False,
)

holes_schema = DataFrameSchema(
    {
        "hole_number": Column(int, Check.in_range(1, 18), nullable=False, unique=True),
        "par": Column(int, Check.isin([3, 4, 5]), nullable=False),
        "stroke_index": Column(int, Check.in_range(1, 18), nullable=False, unique=True),
        "yards_blues": Column(int, Check.gt(0), nullable=False),
        "yards_whites": Column(int, Check.gt(0), nullable=False),
        "yards_yellows": Column(int, Check.gt(0), nullable=False),
        "yards_reds": Column(int, Check.gt(0), nullable=False),
    },
    strict=False,
)


def test_members_conform(load_table):
    df = load_table("members")
    members_schema.validate(df, lazy=True)
    assert bool(df["is_admin"].any()), "expected at least one admin member"


def test_tee_times_conform(load_table):
    df = load_table("tee_times")
    tee_times_schema.validate(df, lazy=True)
    # Seed creates slots for today..today+6. Allow a day's tolerance either side
    # for timezone skew between the test runner and the container.
    dates = pd.to_datetime(df["date"]).dt.date
    today = date.today()
    assert dates.min() >= today - timedelta(days=1), "tee times should not be stale/in the past"
    assert dates.max() <= today + timedelta(days=7), "tee times should be within the seeded window"


def test_competitions_conform(load_table):
    df = load_table("competitions")
    competitions_schema.validate(df, lazy=True)


def test_holes_conform(load_table):
    df = load_table("holes")
    holes_schema.validate(df, lazy=True)
    assert len(df) == 18, "a full course is 18 holes"
    assert sorted(df["hole_number"]) == list(range(1, 19)), "hole numbers must be the set 1..18"
    # Stroke index must be a permutation of 1..18 — each difficulty rank used once.
    assert sorted(df["stroke_index"]) == list(range(1, 19)), "stroke index must be a 1..18 permutation"
    # Tee lengths run longest (blues) to shortest (reds).
    assert (df["yards_blues"] >= df["yards_whites"]).all()
    assert (df["yards_whites"] >= df["yards_yellows"]).all()
    assert (df["yards_yellows"] >= df["yards_reds"]).all()
