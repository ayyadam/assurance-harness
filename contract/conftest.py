"""Fixtures for contract tests against the golf-web-app JSON API.

These tests require the SUT to be running and reachable at SUT_BASE_URL
(default http://localhost:5000). Bring it up first, for example:

    cd ../golf-web-app
    docker compose up -d
    docker compose exec web python seed.py

Then, from this repo:

    uv run pytest contract/

Contract tests are intentionally excluded from the default `pytest` run
(which targets tests/ and needs no SUT). Run them explicitly as above.
"""

import os
from pathlib import Path

import pytest
import requests
import schemathesis
from schemathesis.config import SchemathesisConfig

SUT_BASE_URL = os.getenv("SUT_BASE_URL", "http://localhost:5000")
OPENAPI_URL = f"{SUT_BASE_URL}/api/v1/openapi.json"

# schemathesis.toml lives at the repo root; load it explicitly so the config
# is picked up regardless of the working directory pytest runs from.
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "schemathesis.toml"

# Seeded member credentials (see golf-web-app/seed.py).
SEED_USERNAME = os.getenv("SUT_USERNAME", "john.smith")
SEED_PASSWORD = os.getenv("SUT_PASSWORD", "Password1")


@pytest.fixture(scope="session")
def api_schema():
    """Load the OpenAPI schema from the running SUT.

    wait_for_schema gives the SUT a few seconds to come up, which smooths
    over container start-up races in CI.
    """
    config = SchemathesisConfig.from_path(_CONFIG_PATH)
    return schemathesis.openapi.from_url(OPENAPI_URL, wait_for_schema=15.0, config=config)


@pytest.fixture(scope="session")
def auth_token():
    """Obtain a bearer token from a seeded member account.

    Authenticated operations (members/me, booking creation) need this; the
    token is harmless on public operations, so it is applied to every
    generated request.
    """
    resp = requests.post(
        f"{SUT_BASE_URL}/api/v1/auth/token",
        json={"username": SEED_USERNAME, "password": SEED_PASSWORD},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]
