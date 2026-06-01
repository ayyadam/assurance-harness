"""Parse the risk register markdown into structured Risk records.

The agent feeds these to the LLM as JSON so it ranks against the *real* register
rather than a snapshot embedded in a prompt. When the register changes (rows
added, mitigations updated), the agent's view changes with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REGISTER_PATH = Path(__file__).resolve().parent.parent / "docs" / "risk-register.md"

# Active-risks table rows look like:
# | R-001 | Risk text ... | M | M | 4 | **mitigated** | Mitigation text ... |
_ROW = re.compile(
    r"^\|\s*(R-\d{3})\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|"
    r"\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$"
)


# Canonical layer names + the keywords we look for in each register row's
# mitigation column. First match wins, so order from specific to general.
# This is the closed vocabulary the agent's `covered_by` is pinned to in v2 v1
# — it replaces the v1 free-text field, which sometimes returned a literal list
# of action versions (PR #8 R-017) or a misspelt layer name.
_LAYER_HINTS: list[tuple[str, list[str]]] = [
    ("ai_evaluation/", ["ai_evaluation/", "phase-8 eval", "phase 8 eval", "golden set", "LLM-judge"]),
    ("Schemathesis contract suite", ["Schemathesis"]),
    ("axe-core sweep", ["axe-core", "axe-playwright"]),
    ("k6 performance gate", ["k6"]),
    ("pandera data quality", ["pandera"]),
    ("Playwright functional suite", ["Playwright", "functional/", "functional layer"]),
    ("Per-route unit tests", ["test_admin_routes.py", "Unit tests verify"]),
    (
        "CI workflow configuration",
        ["actions/checkout", "Workflow trigger", "hosted runners", "actions/upload-artifact"],
    ),
    ("conftest.py SQLite pragma", ["PRAGMA foreign_keys"]),
    ("Synthetic seed data", ["synthetic", "fixture data is"]),
]

_OPEN = "none (open, no layer)"
_ACCEPTED = "accepted (out of scope)"
_UNCLASSIFIED = "see register (no canonical layer detected)"


def _extract_layer(status: str, mitigation: str) -> str:
    """Derive a canonical covered_by from the register row's status + mitigation.

    Honest about the three failure modes: open with no plan → ``_OPEN``;
    accepted → ``_ACCEPTED``; mitigated but the heuristic couldn't pick a
    layer → ``_UNCLASSIFIED`` (visible signal that the LAYER_HINTS need an
    entry, rather than silently picking the wrong layer).
    """
    s = status.lower()
    if s == "open":
        return _OPEN
    if s == "accepted":
        return _ACCEPTED
    mit = mitigation.lower()
    for layer, keywords in _LAYER_HINTS:
        if any(k.lower() in mit for k in keywords):
            return layer
    return _UNCLASSIFIED


@dataclass
class Risk:
    id: str
    description: str
    likelihood: str  # L | M | H | —
    impact: str  # L | M | H | —
    score: str  # numeric or "—"
    status: str  # open | mitigated | partially mitigated | accepted
    mitigation: str
    covered_by_canonical: str = ""  # filled by parse_register()
    is_gap_deterministic: bool = False  # filled by parse_register() — true iff status == open

    def to_prompt_dict(self) -> dict:
        """Compact dict for the LLM prompt — keeps token budget reasonable."""
        return {
            "id": self.id,
            "risk": self.description,
            "L": self.likelihood,
            "I": self.impact,
            "score": self.score,
            "status": self.status,
            "mitigation": self.mitigation,
        }


def _strip_md(text: str) -> str:
    """Remove markdown emphasis and inline links for a cleaner prompt."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.strip()


def parse_register(path: Path = DEFAULT_REGISTER_PATH) -> list[Risk]:
    """Parse the Active risks table into Risk records."""
    text = path.read_text(encoding="utf-8")
    in_active = False
    risks: list[Risk] = []
    for line in text.splitlines():
        if line.startswith("## Active risks"):
            in_active = True
            continue
        if in_active and line.startswith("## "):  # next section
            break
        if not in_active:
            continue
        m = _ROW.match(line)
        if not m:
            continue
        rid, desc, lik, imp, score, status, mit = m.groups()
        status_clean = _strip_md(status)
        mitigation_clean = _strip_md(mit)
        risks.append(
            Risk(
                id=rid,
                description=_strip_md(desc),
                likelihood=_strip_md(lik),
                impact=_strip_md(imp),
                score=_strip_md(score),
                status=status_clean,
                mitigation=mitigation_clean,
                covered_by_canonical=_extract_layer(status_clean, mitigation_clean),
                is_gap_deterministic=(status_clean.lower() == "open"),
            )
        )
    return risks
