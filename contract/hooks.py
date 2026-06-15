"""Schemathesis hooks for the contract evidence run (loaded via SCHEMATHESIS_HOOKS).

The tee-time / booking operations take a `tee_time_id` path parameter. Pure
fuzzing generates random integers, so their success paths (200/201) are only hit
by luck and the run is example-budget-sensitive. This hook injects a REAL,
bookable `tee_time_id` (fetched once from `GET /tee-times`) into those operations
so the referential success + business-logic paths are exercised **deterministically**
every run.

Profile-driven (base URL + auth from [core.profile]). Scoped to the evidence CLI
run only — `contract/evidence.py` sets the env var for its subprocess, NOT
globally — so the pytest contract gate is unaffected.

Trade-off: those operations no longer receive random (non-existent) ids, so the
404-on-missing path isn't fuzzed here — a deliberate swap of trivial 404 coverage
for guaranteed valid-id coverage. (The stateful phase, once the SUT declares
OpenAPI links, will add sequence coverage on top — PR B/C.)
"""

from __future__ import annotations

import requests
import schemathesis

from core.profile import load_profile

_PATH_PARAM = "tee_time_id"
_cached_id: int | None = None
_fetched = False


def inject_real_id(path_parameters: dict | None, real_id: int | None) -> dict | None:
    """Pure helper (unit-tested): swap a real id into `tee_time_id` when both the
    parameter and a real id are present; otherwise pass through untouched."""
    if path_parameters and real_id is not None and _PATH_PARAM in path_parameters:
        return {**path_parameters, _PATH_PARAM: real_id}
    return path_parameters


def _fetch_real_tee_time_id() -> int | None:
    """Fetch a real, preferably bookable, tee_time_id once and cache it."""
    global _cached_id, _fetched
    if _fetched:
        return _cached_id
    _fetched = True
    profile = load_profile()
    try:
        token = requests.post(
            profile.token_url,
            json={"username": profile.auth.username, "password": profile.auth.password},
            timeout=15,
        ).json()["access_token"]
        resp = requests.get(
            f"{profile.base_url}/api/v1/tee-times",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        tee_times = resp.json() or []
        bookable = [t for t in tee_times if t.get("is_available") and (t.get("slots_remaining") or 0) > 0]
        chosen = (bookable or tee_times)[0] if tee_times else None
        _cached_id = chosen["id"] if chosen else None
        print(f"[contract-hooks] injecting real {_PATH_PARAM}={_cached_id} (bookable={bool(bookable)})")
    except Exception as exc:  # noqa: BLE001 - best-effort; fall back to fuzzed ids
        print(f"[contract-hooks] could not fetch a real {_PATH_PARAM} ({exc}); using fuzzed ids")
        _cached_id = None
    return _cached_id


@schemathesis.hook
def map_path_parameters(context, path_parameters):
    return inject_real_id(path_parameters, _fetch_real_tee_time_id())
