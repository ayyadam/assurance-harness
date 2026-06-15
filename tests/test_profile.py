"""Gated unit tests for the SUT profile loader (B-i, Workstream B).

No SUT, no network — these run in the standard pytest gate. They assert the
config seam behaves: the golf-web-app profile loads with the expected values,
env knobs override the file (so existing CI/local workflows are unaffected), a
custom profile can be selected by path/env, and missing required keys fail loud.
"""

from __future__ import annotations

import pytest

from core.profile import load_profile

# golf-web-app facts shouldn't bleed in from the ambient environment.
_SUT_ENV = ("SUT_BASE_URL", "SUT_USERNAME", "SUT_PASSWORD", "ASSURANCE_PROFILE")


@pytest.fixture
def clean_env(monkeypatch):
    for var in _SUT_ENV:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_loads_golf_web_app_profile(clean_env):
    p = load_profile()
    assert p.name == "golf-web-app"
    assert p.base_url == "http://localhost:5000"
    assert p.openapi_url == "http://localhost:5000/api/v1/openapi.json"
    assert p.token_url == "http://localhost:5000/api/v1/auth/token"
    assert p.auth.username == "john.smith"
    assert ("home", "/") in p.accessibility.public_pages
    assert ("book-tee-time", "/member/book-tee-time") in p.accessibility.member_pages


def test_env_overrides_base_url_and_strips_trailing_slash(clean_env):
    clean_env.setenv("SUT_BASE_URL", "http://staging:8080/")
    p = load_profile()
    assert p.base_url == "http://staging:8080"
    assert p.openapi_url == "http://staging:8080/api/v1/openapi.json"


def test_env_overrides_credentials(clean_env):
    clean_env.setenv("SUT_USERNAME", "alice")
    clean_env.setenv("SUT_PASSWORD", "s3cret")
    p = load_profile()
    assert p.auth.username == "alice" and p.auth.password == "s3cret"


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_custom_profile_selected_by_env(clean_env, tmp_path):
    prof = _write(
        tmp_path / "other.yaml",
        "name: other-sut\nbase_url: http://other:9000\nauth:\n  token_endpoint: /tok\n  username: u\n  password: p\n",
    )
    clean_env.setenv("ASSURANCE_PROFILE", str(prof))
    p = load_profile()
    assert p.name == "other-sut" and p.base_url == "http://other:9000"
    assert p.accessibility.public_pages == []  # optional section defaults empty


def test_explicit_path_arg_beats_env(clean_env, tmp_path):
    clean_env.setenv("ASSURANCE_PROFILE", "/does/not/exist.yaml")
    prof = _write(
        tmp_path / "explicit.yaml",
        "name: explicit\nbase_url: http://x\nauth:\n  token_endpoint: /t\n  username: u\n  password: p\n",
    )
    assert load_profile(prof).name == "explicit"


def test_missing_base_url_raises(clean_env, tmp_path):
    prof = _write(tmp_path / "bad.yaml", "name: bad\n")
    with pytest.raises(ValueError, match="base_url"):
        load_profile(prof)


def test_missing_auth_raises(clean_env, tmp_path):
    prof = _write(tmp_path / "bad.yaml", "name: bad\nbase_url: http://x\n")
    with pytest.raises(ValueError, match="auth"):
        load_profile(prof)


def test_missing_file_raises(clean_env):
    with pytest.raises(FileNotFoundError):
        load_profile("/no/such/profile.yaml")
