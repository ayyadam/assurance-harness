"""Declarative SUT profile — the config seam that makes the harness re-pointable.

Instead of hardcoding golf-web-app facts in each pillar, the SUT-specific values
live in a profile YAML (`profiles/<name>.yaml`) loaded here. Pointing the harness
at a different application becomes "write a new profile", not "edit the pillars"
— `golf-web-app` is simply profile #1.

Resolution order for the profile path: explicit arg > `$ASSURANCE_PROFILE` > the
default golf-web-app profile. A few long-standing env knobs (`SUT_BASE_URL`,
`SUT_USERNAME`, `SUT_PASSWORD`) still override the profile so existing CI/local
workflows are unaffected.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent.parent / "profiles" / "golf-web-app.yaml"


@dataclass(frozen=True)
class AuthConfig:
    """How to obtain a token for authenticated calls (the SUT's auth recipe)."""

    token_endpoint: str  # path appended to base_url, e.g. /api/v1/auth/token
    username: str
    password: str


@dataclass(frozen=True)
class AccessibilityConfig:
    """Pages the a11y sweep visits, as (name, path) pairs."""

    public_pages: list[tuple[str, str]]
    member_pages: list[tuple[str, str]]


@dataclass(frozen=True)
class ReferentialId:
    """How to obtain a real id for a path parameter (so contract fuzzing of
    parameterised operations hits success paths instead of fuzzed 404s). Generic
    REST pattern: GET `list_endpoint`, take `id_field` from a (preferably
    `prefer_fields`-truthy) item, inject into `path_param`."""

    path_param: str
    list_endpoint: str
    id_field: str = "id"
    prefer_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoverageFloor:
    """Minimum coverage the contract gate enforces on top of Schemathesis's own
    pass/fail: every operation the spec declares must be exercised at least
    `min_cases_per_op` times, and every declared OpenAPI link traversed at least
    `min_link_traversals` times in the stateful phase. App-agnostic — the
    operation and link sets are read from the spec, never hardcoded."""

    min_cases_per_op: int = 1
    min_link_traversals: int = 1


@dataclass(frozen=True)
class ContractConfig:
    """SUT-specific facts the contract pillar needs (kept here, not in the engine)."""

    referential_ids: list[ReferentialId]
    coverage_floor: CoverageFloor = field(default_factory=CoverageFloor)


@dataclass(frozen=True)
class Profile:
    name: str
    base_url: str
    openapi_spec_path: str
    auth: AuthConfig
    accessibility: AccessibilityConfig
    contract: ContractConfig

    @property
    def openapi_url(self) -> str:
        return self.base_url + self.openapi_spec_path

    @property
    def token_url(self) -> str:
        return self.base_url + self.auth.token_endpoint


def _pages(raw: list) -> list[tuple[str, str]]:
    return [(str(name), str(path)) for name, path in raw]


def _referential_ids(raw: list) -> list[ReferentialId]:
    out: list[ReferentialId] = []
    for r in raw:
        if not (r.get("path_param") and r.get("list_endpoint")):
            raise ValueError("each contract.referential_ids entry needs 'path_param' and 'list_endpoint'")
        out.append(
            ReferentialId(
                path_param=str(r["path_param"]),
                list_endpoint=str(r["list_endpoint"]),
                id_field=str(r.get("id_field") or "id"),
                prefer_fields=tuple(r.get("prefer_fields") or ()),
            )
        )
    return out


def _coverage_floor(raw: dict | None) -> CoverageFloor:
    raw = raw or {}
    return CoverageFloor(
        min_cases_per_op=int(raw.get("min_cases_per_op", 1)),
        min_link_traversals=int(raw.get("min_link_traversals", 1)),
    )


def load_profile(path: str | os.PathLike | None = None) -> Profile:
    """Load and validate a SUT profile. Env overrides (SUT_BASE_URL / SUT_USERNAME
    / SUT_PASSWORD) win over the file so existing workflows keep working."""
    profile_path = Path(path or os.getenv("ASSURANCE_PROFILE") or DEFAULT_PROFILE_PATH)
    if not profile_path.exists():
        raise FileNotFoundError(f"SUT profile not found: {profile_path}")
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}

    name = data.get("name")
    if not name:
        raise ValueError(f"SUT profile {profile_path} needs a 'name'")

    base_url = (os.getenv("SUT_BASE_URL") or data.get("base_url") or "").rstrip("/")
    if not base_url:
        raise ValueError(f"SUT profile {profile_path} needs 'base_url' (or set $SUT_BASE_URL)")

    auth_raw = data.get("auth") or {}
    username = os.getenv("SUT_USERNAME") or auth_raw.get("username")
    password = os.getenv("SUT_PASSWORD") or auth_raw.get("password")
    token_endpoint = auth_raw.get("token_endpoint")
    if not (username and password and token_endpoint):
        raise ValueError(f"SUT profile {profile_path} 'auth' needs token_endpoint, username, password")

    a11y_raw = data.get("accessibility") or {}
    contract_raw = data.get("contract") or {}
    return Profile(
        name=str(name),
        base_url=base_url,
        openapi_spec_path=data.get("openapi_spec_path") or "/api/v1/openapi.json",
        auth=AuthConfig(token_endpoint=token_endpoint, username=username, password=password),
        accessibility=AccessibilityConfig(
            public_pages=_pages(a11y_raw.get("public_pages") or []),
            member_pages=_pages(a11y_raw.get("member_pages") or []),
        ),
        contract=ContractConfig(
            referential_ids=_referential_ids(contract_raw.get("referential_ids") or []),
            coverage_floor=_coverage_floor(contract_raw.get("coverage_floor")),
        ),
    )
