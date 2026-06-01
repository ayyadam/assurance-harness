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


@dataclass
class Risk:
    id: str
    description: str
    likelihood: str  # L | M | H | —
    impact: str  # L | M | H | —
    score: str  # numeric or "—"
    status: str  # open | mitigated | partially mitigated | accepted
    mitigation: str

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
        risks.append(
            Risk(
                id=rid,
                description=_strip_md(desc),
                likelihood=_strip_md(lik),
                impact=_strip_md(imp),
                score=_strip_md(score),
                status=_strip_md(status),
                mitigation=_strip_md(mit),
            )
        )
    return risks
