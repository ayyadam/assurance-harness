"""Unit tests for ``deterministic_auth_finding`` — the spec-aware sharpening.

F-020 changed the rule: a 2xx response on an ``unauth``/``wrong_creds`` probe
is only an ``auth_boundary_concern`` when the spec marks the endpoint as
requiring auth. When the spec documents it as public, the same 2xx becomes
``documented_public_endpoint`` (informational, not a finding).

These tests fix that branching in place so future contributors can't
silently regress it back to the pre-F-020 "any anonymous 2xx is a concern"
behaviour.
"""

from __future__ import annotations

import pytest

from explore_agent.judge import deterministic_auth_finding
from explore_agent.probe import Probe, Variant
from explore_agent.spec import Endpoint


def _endpoint(*, security=None, global_security=None) -> Endpoint:
    operation: dict[str, object] = {}
    if security is not None:
        operation["security"] = security
    return Endpoint(
        method="GET",
        path="/api/v1/example",
        summary="example",
        operation=operation,
        components={},
        global_security=global_security,
    )


def _probe(*, endpoint: Endpoint, status: int, auth_mode: str = "unauth") -> Probe:
    return Probe(
        endpoint=endpoint,
        variant=Variant(label="happy", body=None, rationale="test"),
        request_url="http://test/api/v1/example",
        request_method="GET",
        request_body=None,
        status=status,
        latency_ms=1.0,
        response_body=None,
        response_text="",
        auth_mode=auth_mode,
    )


class TestSpecRequiresAuth:
    """Operation-level security set — endpoint is documented as auth-required."""

    @pytest.fixture
    def endpoint(self) -> Endpoint:
        return _endpoint(security=[{"BearerAuth": []}])

    def test_401_is_expected(self, endpoint: Endpoint) -> None:
        finding = deterministic_auth_finding(_probe(endpoint=endpoint, status=401))
        assert finding.category == "expected"

    def test_403_is_expected(self, endpoint: Endpoint) -> None:
        finding = deterministic_auth_finding(_probe(endpoint=endpoint, status=403))
        assert finding.category == "expected"

    def test_200_is_auth_boundary_concern(self, endpoint: Endpoint) -> None:
        finding = deterministic_auth_finding(_probe(endpoint=endpoint, status=200))
        assert finding.category == "auth_boundary_concern"
        assert finding.severity == "high"
        assert "spec/impl auth drift" in finding.rationale.lower()

    def test_500_is_unexpected_5xx(self, endpoint: Endpoint) -> None:
        finding = deterministic_auth_finding(_probe(endpoint=endpoint, status=500))
        assert finding.category == "unexpected_5xx"


class TestSpecAllowsAnonymous:
    """No operation-level security and no global — endpoint is documented public."""

    @pytest.fixture
    def endpoint(self) -> Endpoint:
        return _endpoint()

    def test_200_is_documented_public_endpoint(self, endpoint: Endpoint) -> None:
        finding = deterministic_auth_finding(_probe(endpoint=endpoint, status=200))
        assert finding.category == "documented_public_endpoint"
        assert finding.severity == "low"
        assert "spec documents" in finding.rationale.lower()

    def test_401_still_expected_when_impl_stricter_than_spec(self, endpoint: Endpoint) -> None:
        # An impl that returns 401 on an endpoint the spec says is public is
        # stricter than documented — not a concern, the boundary held.
        finding = deterministic_auth_finding(_probe(endpoint=endpoint, status=401))
        assert finding.category == "expected"


class TestExplicitlyEmptyOperationSecurity:
    """Operation-level ``security: []`` overrides any global — public override."""

    def test_explicit_empty_with_global_required_is_public(self) -> None:
        endpoint = _endpoint(security=[], global_security=[{"BearerAuth": []}])
        finding = deterministic_auth_finding(_probe(endpoint=endpoint, status=200))
        assert finding.category == "documented_public_endpoint"


class TestGlobalSecurityInheritance:
    """No operation-level security — falls back to global."""

    def test_inherits_global_required(self) -> None:
        endpoint = _endpoint(global_security=[{"BearerAuth": []}])
        finding = deterministic_auth_finding(_probe(endpoint=endpoint, status=200))
        assert finding.category == "auth_boundary_concern"

    def test_inherits_global_absent(self) -> None:
        endpoint = _endpoint(global_security=None)
        finding = deterministic_auth_finding(_probe(endpoint=endpoint, status=200))
        assert finding.category == "documented_public_endpoint"


class TestAuthModeReachesRationale:
    """Both auth_mode values surface in the rationale text."""

    @pytest.fixture
    def endpoint(self) -> Endpoint:
        return _endpoint(security=[{"BearerAuth": []}])

    def test_unauth_named_in_concern(self, endpoint: Endpoint) -> None:
        finding = deterministic_auth_finding(_probe(endpoint=endpoint, status=200, auth_mode="unauth"))
        assert "unauth" in finding.rationale

    def test_wrong_creds_named_in_concern(self, endpoint: Endpoint) -> None:
        finding = deterministic_auth_finding(_probe(endpoint=endpoint, status=200, auth_mode="wrong_creds"))
        assert "wrong_creds" in finding.rationale
