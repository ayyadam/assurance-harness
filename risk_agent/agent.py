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
    "score each register risk by how plausibly THIS DIFF could trigger it.\n\n"
    "Relevance scale — emit ONLY risks scoring 2 or 3. Skip 0 and 1 entirely:\n"
    "  3 — direct: the diff plainly touches code, schema, or surface that this risk "
    "      worries about.\n"
    "  2 — plausible: the diff touches adjacent code, contract, template, or input path; "
    "      a reasonable reviewer would check this risk on this PR.\n"
    "  1 — speculative: you can see a connection but it requires several inferential steps. "
    "      DO NOT EMIT.\n"
    "  0 — not raised by this diff. DO NOT EMIT.\n\n"
    "Output rules:\n"
    "  - Only reference risk IDs that appear in the register. Do not invent IDs.\n"
    "  - Each ranked risk needs: id, relevance (2 or 3), rationale (1-2 sentences "
    "    anchored in specific changed files or function names), action (the concrete next "
    "    step a reviewer should take — 're-run the contract suite', 'add a golden-set case "
    "    for X', 'manual probe of Y').\n"
    "  - Note: covered_by and is_gap are NOT model outputs in this version — they are "
    "    derived deterministically from the register row's status and mitigation column. "
    "    Focus your judgement on relevance, rationale, and action.\n"
    "  - Suggest up to 4 exploratory probes — short, concrete things a human reviewer could "
    "    try in a browser or with curl that the automated layers won't have run. Probes "
    "    should target THIS diff, not generic advice.\n"
    "  - Begin with a one-sentence factual summary of what this PR changes from an "
    "    assurance perspective.\n"
)


def _schema(risk_ids: list[str]) -> dict:
    """JSON schema for the agent's structured output.

    v2 v1: drops ``covered_by`` and ``is_gap`` (now derived deterministically from
    the register), adds ``relevance`` constrained to 2 or 3 (so the model self-
    filters speculative tail entries rather than padding the ranking).
    """
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "ranked_risks": {
                "type": "array",
                "maxItems": 8,  # generous upper bound; relevance filter keeps it tight
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": risk_ids},
                        "relevance": {"type": "integer", "enum": [2, 3]},
                        "rationale": {"type": "string"},
                        "action": {"type": "string"},
                    },
                    "required": ["id", "relevance", "rationale", "action"],
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
    """Call the agent and return the structured ranking.

    v2 v1 post-processing: ``covered_by`` and ``is_gap`` are looked up from the
    parsed register (the source of truth), not the model. Ranking is sorted by
    descending relevance so the reviewer reads top-down without re-checking
    score order. The model still drives summary, rationale, action, probes.
    """
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

    by_id = {r.id: r for r in risks}
    enriched: list[dict] = []
    for rr in parsed["ranked_risks"]:
        risk = by_id.get(rr["id"])
        if risk is None:  # schema enum makes this unreachable, but be safe
            continue
        enriched.append(
            {
                "id": rr["id"],
                "relevance": rr["relevance"],
                "rationale": rr["rationale"],
                "action": rr["action"],
                "covered_by": risk.covered_by_canonical,
                "is_gap": risk.is_gap_deterministic,
            }
        )
    enriched.sort(key=lambda r: (-r["relevance"], r["id"]))

    return AgentResult(
        summary=parsed["summary"],
        ranked_risks=enriched,
        exploratory_probes=parsed["exploratory_probes"],
        model=model,
    )
