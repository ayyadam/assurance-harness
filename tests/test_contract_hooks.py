"""Gated unit tests for the contract hook's pure injection logic.

No SUT, no network, no Schemathesis run — just the rule: swap a real id into
`tee_time_id` when both the parameter and a real id are present; otherwise leave
the generated parameters untouched."""

from __future__ import annotations

from contract.hooks import inject_real_id


def test_injects_real_id_when_param_present():
    assert inject_real_id({"tee_time_id": 7}, 325) == {"tee_time_id": 325}


def test_preserves_sibling_params():
    assert inject_real_id({"tee_time_id": 7, "other": "x"}, 325) == {"tee_time_id": 325, "other": "x"}


def test_leaves_unrelated_params_untouched():
    assert inject_real_id({"other": 1}, 325) == {"other": 1}


def test_passthrough_when_no_real_id():
    assert inject_real_id({"tee_time_id": 7}, None) == {"tee_time_id": 7}


def test_passthrough_when_no_params():
    assert inject_real_id(None, 325) is None
    assert inject_real_id({}, 325) == {}
