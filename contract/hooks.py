"""Schemathesis hooks for the contract evidence run (loaded via SCHEMATHESIS_HOOKS).

Parameterised/write operations take a referential path parameter (e.g. an id of
an existing resource). Pure fuzzing generates random values, so those operations'
success paths are only hit by luck. This hook injects a REAL id into them so the
referential success + business-logic paths are exercised **deterministically**.

It is **app-agnostic**: the SUT-specific facts (which path param, which collection
endpoint to read, which field is the id, how to prefer a usable item) live in the
active profile under `contract.referential_ids` ([core.profile]). This module
contains zero SUT knowledge — re-point at another SUT via its profile and the
same hook works. (For referential logic too complex to express as data —
create-then-use, computed values — the escape hatch is a per-profile hooks
module; not needed for the current SUTs.)

Scoped to the evidence CLI run only — `contract/evidence.py` sets the env var for
its subprocess, NOT globally — so the pytest contract gate is unaffected.

Trade-off: targeted operations no longer receive random (non-existent) ids, so
the 404-on-missing path isn't fuzzed here — a deliberate swap of trivial 404
coverage for guaranteed valid-id coverage.
"""

from __future__ import annotations

import requests
import schemathesis

from core.profile import Profile, ReferentialId, load_profile

_resolved: dict[str, object] | None = None  # path_param -> real id, cached for the run


def inject_real_ids(path_parameters: dict | None, resolved: dict) -> dict | None:
    """Pure helper (unit-tested): replace any path parameter we have a real id for;
    leave everything else untouched. Returns the original object if nothing changed."""
    if not path_parameters:
        return path_parameters
    updated = dict(path_parameters)
    changed = False
    for name, real_id in resolved.items():
        if name in updated and real_id is not None:
            updated[name] = real_id
            changed = True
    return updated if changed else path_parameters


def _auth_token(profile: Profile) -> str | None:
    try:
        resp = requests.post(
            profile.token_url,
            json={"username": profile.auth.username, "password": profile.auth.password},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception:  # noqa: BLE001 - token is best-effort; public list endpoints may not need it
        return None


def _resolve_one(profile: Profile, token: str | None, spec: ReferentialId) -> object | None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = requests.get(f"{profile.base_url}{spec.list_endpoint}", headers=headers, timeout=15)
    resp.raise_for_status()
    items = resp.json() or []
    if not isinstance(items, list):
        return None
    preferred = [i for i in items if isinstance(i, dict) and all(i.get(f) for f in spec.prefer_fields)]
    chosen = (preferred or [i for i in items if isinstance(i, dict)] or [None])[0]
    return chosen.get(spec.id_field) if isinstance(chosen, dict) else None


def _resolve_referential_ids() -> dict[str, object]:
    """Resolve every profile-declared referential id once, and cache for the run."""
    global _resolved
    if _resolved is not None:
        return _resolved
    profile = load_profile()
    token = _auth_token(profile)
    out: dict[str, object] = {}
    for spec in profile.contract.referential_ids:
        try:
            real_id = _resolve_one(profile, token, spec)
            if real_id is not None:
                out[spec.path_param] = real_id
        except Exception as exc:  # noqa: BLE001 - fall back to fuzzed ids for this param
            print(f"[contract-hooks] could not resolve {spec.path_param} from {spec.list_endpoint} ({exc})")
    _resolved = out
    print(f"[contract-hooks] resolved referential ids: {out}")
    return out


@schemathesis.hook
def map_path_parameters(context, path_parameters):
    return inject_real_ids(path_parameters, _resolve_referential_ids())
