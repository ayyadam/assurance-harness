"""Fixtures for data-quality checks against golf-web-app's database.

These read the SUT's live Postgres tables into DataFrames and validate them
with pandera. They require the SUT running with its database reachable at
SUT_DB_URL (default points at the compose-exposed Postgres on localhost:5432):

    cd ../golf-web-app
    docker compose up -d
    docker compose exec web python seed.py

Then, from this repo:

    uv run pytest data_quality/

Data-quality tests are excluded from the default `pytest` run (which targets
tests/ and needs no SUT). Run them explicitly as above.
"""

import os
from collections.abc import Callable

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

# Matches docker-compose.yml: agc_user / agc_pass / agc_db on the exposed 5432.
SUT_DB_URL = os.getenv(
    "SUT_DB_URL",
    "postgresql+psycopg2://agc_user:agc_pass@localhost:5432/agc_db",
)


@pytest.fixture(scope="session")
def engine() -> Engine:
    eng = create_engine(SUT_DB_URL)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def load_table(engine: Engine) -> Callable[[str], pd.DataFrame]:
    """Return a loader that reads a whole table into a DataFrame."""

    def _load(name: str) -> pd.DataFrame:
        return pd.read_sql_table(name, engine)

    return _load
