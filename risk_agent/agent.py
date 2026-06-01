"""Ollama-backed risk-prioritisation agent.

Reads the parsed risk register + a diff bundle, and returns a structured
ranking. Uses Ollama structured output so the LLM is constrained to emit only
known risk IDs and the shape the renderer expects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import ollama

from risk_agent.diff import DiffBundle
from risk_agent.register import Risk

DEFAULT_MODEL = "qwen2.5:32b-instruct-q4_K_M"


_SYSTEM = (
    "You are a Digital Assurance Engineer helping a reviewer prioritise testing for a pull "
    "request against a documented risk register. The register is the source of truth for "
    "what could go wrong with this system. Your job: read the diff and the register, and "
    "rank the risks by how plausibly THIS DIFF could trigger them.\n\n"
    "Output rules:\n"
    "  - Only reference risk IDs that appear in the register. Do not invent IDs.\n"
    "  - Rank at most the top 6 risks raised by the diff. A risk that the diff plainly does "
    "    not touch should not appear in the ranking.\n"
    "  - For each ranked risk: explain WHY this diff raises it in one or two sentences, "
    "    grounding the reasoning in specific changed files where possible.\n"
    "  - covered_by + is_gap depend on the STATUS column, NOT on whether you think the "
    "    coverage is sufficient. Rules:\n"
    "      * status 'mitigated' or 'partially mitigated' => is_gap=false. Set covered_by "
    "        to the layer named in the mitigation column (e.g. 'Schemathesis contract "
    "        suite', 'ai_evaluation/', 'k6 thresholds-as-code', 'axe-core sweep').\n"
    "      * status 'open' with no planned/existing layer => is_gap=true, covered_by='none'.\n"
    "      * status 'accepted' => is_gap=false, covered_by='accepted (out of scope)'.\n"
    "  - 'action' is the concrete next step a reviewer should take: 're-run the contract "
    "    suite', 'add a golden-set case for X', 'manual probe of Y', etc. Be specific.\n"
    "  - Suggest up to 4 exploratory probes — short, concrete things a human reviewer could "
    "    try in a browser or with curl that the automated layers won't have run. Probes "
    "    should target THIS diff, not generic advice.\n"
    "  - Begin with a one-sentence 'summary' of what this PR changes from an assurance "
    "    perspective. Stay factual; do not editorialise about code quality.\n"
)


def _schema(risk_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "ranked_risks": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": risk_ids},
                        "rationale": {"type": "string"},
                        "covered_by": {"type": "string"},
                        "action": {"type": "string"},
                        "is_gap": {"type": "boolean"},
                    },
                    "required": ["id", "rationale", "covered_by", "action", "is_gap"],
                },
            },
            "exploratory_probes": {
                "type": "array",
                "maxItems": 4,
                "items": {"type": "string"},
            },
        },
        "required": ["summary", "ranked_risks", "exploratory_probes"],
    }


@dataclass
class AgentResult:
    summary: str
    ranked_risks: list[dict]
    exploratory_probes: list[str]
    model: str

    def to_json(self) -> dict:
        return {
            "summary": self.summary,
            "ranked_risks": self.ranked_risks,
            "exploratory_probes": self.exploratory_probes,
            "model": self.model,
        }


def _user_message(risks: list[Risk], diff: DiffBundle) -> str:
    register_json = json.dumps([r.to_prompt_dict() for r in risks], indent=2)
    file_list = "\n".join(f"  - {p}" for p in diff.files) if diff.files else "  (no files detected)"
    header = ""
    if diff.pr_number is not None:
        header += f"PR #{diff.pr_number} ({diff.repo}): {diff.title}\n\n"
    if diff.truncated:
        header += (
            f"NOTE: diff truncated to keep prompt size manageable "
            f"({diff.total_lines} total lines, body capped at the file boundary preceding the cap).\n\n"
        )
    return (
        f"{header}"
        f"Risk register (JSON):\n{register_json}\n\n"
        f"Changed files:\n{file_list}\n\n"
        f"Diff:\n```diff\n{diff.body}\n```\n\n"
        "Rank the risks raised by this diff."
    )


def prioritise(
    risks: list[Risk],
    diff: DiffBundle,
    model: str = DEFAULT_MODEL,
    host: str | None = None,
) -> AgentResult:
    """Call the agent and return the structured ranking."""
    client = ollama.Client(host=host) if host else ollama
    schema = _schema([r.id for r in risks])
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _user_message(risks, diff)},
        ],
        "format": schema,
        "options": {"temperature": 0},
    }
    try:
        response = client.chat(think=False, **kwargs)
    except ollama.ResponseError:
        response = client.chat(**kwargs)
    parsed = json.loads(response["message"]["content"])
    return AgentResult(
        summary=parsed["summary"],
        ranked_risks=parsed["ranked_risks"],
        exploratory_probes=parsed["exploratory_probes"],
        model=model,
    )
