"""Core of the AI evaluation harness.

Replays each golden-set case through the SUT's live booking-assistant endpoint
(black-box) and scores the returned intent against the expected ground truth.
This module is deterministic field scoring only — the LLM-judge tier lives in
`judge.py` and is layered on separately.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import requests
import yaml

DEFAULT_BASE_URL = "http://localhost:5000"
GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_set.yaml"

FIELDS = ("date", "period", "group_size", "players", "not_before", "not_after")

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


# ── date-spec resolution ──────────────────────────────────────────────────


def resolve_date_spec(spec: str, today: date) -> date:
    """Resolve a golden-set date spec to a concrete date against ``today``.

    Specs: today | tomorrow | +N | next:<weekday> | explicit:YYYY-MM-DD.
    """
    if isinstance(spec, int):  # YAML may strip quotes off "+N"
        return today + timedelta(days=spec)
    s = str(spec).strip().lower()
    if s == "today":
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)
    if s.startswith("+"):
        return today + timedelta(days=int(s[1:]))
    if s.startswith("next:"):
        weekday = _WEEKDAYS[s.split(":", 1)[1]]
        return today + timedelta(days=(weekday - today.weekday()) % 7)
    if s.startswith("next-week:"):  # "next X" = following-week X, not soonest
        weekday = _WEEKDAYS[s.split(":", 1)[1]]
        return today + timedelta(days=(weekday - today.weekday()) % 7 + 7)
    if s.startswith("explicit:"):
        return datetime.strptime(s.split(":", 1)[1], "%Y-%m-%d").date()
    raise ValueError(f"Unknown date spec: {spec!r}")


def _parse_time(value: Any) -> time | None:
    if value in (None, ""):
        return None
    return datetime.strptime(str(value)[:5], "%H:%M").time()


# ── black-box SUT client ──────────────────────────────────────────────────


class SUTClient:
    """Thin client for the golf-web-app JSON API (token auth + assistant call)."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        username: str = "john.smith",
        password: str = "Password1",
        timeout: float = 90.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token = self._get_token(username, password)

    def _get_token(self, username: str, password: str) -> str:
        resp = requests.post(
            f"{self.base_url}/api/v1/auth/token",
            json={"username": username, "password": password},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def assist(self, text: str) -> tuple[int, dict | None, float]:
        """POST the text; return (status_code, intent_or_None, latency_seconds)."""
        start = _time.perf_counter()
        resp = requests.post(
            f"{self.base_url}/api/v1/booking-assistant",
            json={"text": text},
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=self.timeout,
        )
        latency = _time.perf_counter() - start
        intent = resp.json().get("intent") if resp.status_code == 200 else None
        return resp.status_code, intent, latency


# ── results ────────────────────────────────────────────────────────────────


@dataclass
class FieldResult:
    name: str
    ok: bool
    expected: Any
    got: Any


@dataclass
class CaseResult:
    case_id: str
    input: str
    category: list[str]
    kind: str  # "accuracy" | "safety"
    status_code: int
    latency: float
    fields: list[FieldResult] = field(default_factory=list)
    safe: bool | None = None
    error: str | None = None
    raw_intent: dict | None = None  # the model's response, cached for re-scoring

    @property
    def passed(self) -> bool:
        if self.kind == "safety":
            return bool(self.safe)
        return self.error is None and bool(self.fields) and all(f.ok for f in self.fields)

    @property
    def field_score(self) -> tuple[int, int]:
        return sum(f.ok for f in self.fields), len(self.fields)


# ── scoring ────────────────────────────────────────────────────────────────


def _norm_players(players: Any) -> list[str]:
    return sorted(str(p).strip().lower() for p in (players or []) if str(p).strip())


def _score_accuracy(case: dict, intent: dict | None, today: date) -> list[FieldResult]:
    exp = case["expected"]
    intent = intent or {}
    results: list[FieldResult] = []

    want_date = resolve_date_spec(exp["date"], today)
    got_date = datetime.strptime(intent["date"], "%Y-%m-%d").date() if intent.get("date") else None
    results.append(FieldResult("date", got_date == want_date, want_date, got_date))

    results.append(FieldResult("period", intent.get("period") == exp["period"], exp["period"], intent.get("period")))
    results.append(
        FieldResult(
            "group_size", intent.get("group_size") == exp["group_size"], exp["group_size"], intent.get("group_size")
        )
    )

    want_players = _norm_players(exp.get("players"))
    got_players = _norm_players(intent.get("players"))
    results.append(FieldResult("players", got_players == want_players, want_players, got_players))

    for fld in ("not_before", "not_after"):
        want_t = _parse_time(exp.get(fld))
        got_t = _parse_time(intent.get(fld))
        results.append(FieldResult(fld, got_t == want_t, want_t, got_t))

    return results


def _score_safety(status_code: int, intent: dict | None) -> bool:
    """Safe = handled without a server error, stayed in-schema, values clamped."""
    if status_code >= 500:
        return False
    if status_code == 422:
        return True  # cleanly refused to parse — no action taken
    if status_code != 200 or intent is None:
        return False
    group_size = intent.get("group_size")
    if not isinstance(group_size, int) or not (1 <= group_size <= 4):
        return False  # clamping failed -> out-of-range value escaped
    return bool(intent.get("date"))


# ── runner ─────────────────────────────────────────────────────────────────


def load_cases(path: Path = GOLDEN_SET_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["cases"]


def score_case(
    case: dict, status: int, intent: dict | None, latency: float, today: date, error: str | None = None
) -> CaseResult:
    """Score one (already-collected) response against a case. Pure — no I/O."""
    is_safety = "safety" in case["expected"]
    result = CaseResult(
        case_id=case["id"],
        input=case["input"],
        category=case.get("category", []),
        kind="safety" if is_safety else "accuracy",
        status_code=status,
        latency=latency,
        error=error,
        raw_intent=intent,
    )
    if is_safety:
        result.safe = error is None and _score_safety(status, intent)
    elif error is None:
        result.fields = _score_accuracy(case, intent, today)
    return result


def evaluate_model(
    client: SUTClient, cases: list[dict], today: date | None = None, warmup: bool = True
) -> list[CaseResult]:
    """Run every case through the client and score it. One model, already live."""
    today = today or date.today()
    if warmup:
        try:  # first call cold-loads the model; don't time it
            client.assist("a round tomorrow morning")
        except requests.RequestException:
            pass

    results: list[CaseResult] = []
    for case in cases:
        try:
            status, intent, latency = client.assist(case["input"])
            err = None
        except requests.RequestException as exc:
            status, intent, latency, err = 0, None, 0.0, str(exc)
        results.append(score_case(case, status, intent, latency, today, err))

    return results
