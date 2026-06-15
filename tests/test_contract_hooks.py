"""Gated unit tests for the contract hook's pure injection logic.

No SUT, no network, no Schemathesis run — just the rule: replace any path
parameter we resolved a real id for; leave everything else untouched. The hook is
now app-agnostic (SUT facts live in the profile), so these test the generic
mechanism over a resolved {path_param: id} map."""

from __future__ import annotations

from contract.hooks import inject_real_ids


def test_injects_when_param_present():
    assert inject_real_ids({"tee_time_id": 7}, {"tee_time_id": 325}) == {"tee_time_id": 325}


def test_preserves_sibling_params():
    assert inject_real_ids({"tee_time_id": 7, "other": "x"}, {"tee_time_id": 325}) == {"tee_time_id": 325, "other": "x"}


def test_leaves_unrelated_params_untouched():
    assert inject_real_ids({"other": 1}, {"tee_time_id": 325}) == {"other": 1}


def test_passthrough_when_nothing_resolved():
    assert inject_real_ids({"tee_time_id": 7}, {}) == {"tee_time_id": 7}


def test_passthrough_when_no_params():
    assert inject_real_ids(None, {"tee_time_id": 325}) is None
    assert inject_real_ids({}, {"tee_time_id": 325}) == {}


def test_supports_multiple_referential_params():
    assert inject_real_ids({"a": 1, "b": 2}, {"a": 10, "b": 20}) == {"a": 10, "b": 20}
