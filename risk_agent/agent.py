"""Ollama-backed risk-prioritisation agent.

Reads the parsed risk register + a diff bundle, and returns a structured
ranking. Uses Ollama structured output so the LLM is constrained to emit only
known risk IDs and the shape the renderer expects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import ollama

from risk_agent.diff import DiffBundle
from risk_agent.prefilter import candidate_risks
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
    "Subject vs adjacent — a risk is raised by a diff when the diff modifies the SUBJECT "
    "MECHANISM the risk row names, not merely shared terminology or surface. If a risk "
    "concerns concurrency at a transaction boundary and the diff changes natural-language "
    "input parsing on the same feature, that diff does NOT raise the risk — it touches "
    "adjacent code. Read each register row carefully: the description names *what* could "
    "go wrong (the mechanism); the mitigation column hints at *where* the mechanism lives "
    "(the layer or endpoint). Match the diff to the mechanism, not to keywords.\n"
    "  Worked example: a diff improving how the booking assistant interprets time-of-day "
    "  constraints raises R-011 (AI feature correctness — the assistant IS the subject "
    "  mechanism) but does NOT raise R-002 (concurrent overbooking — the transaction "
    "  boundary at POST /book is untouched). Both rows mention 'booking', but only one "
    "  mechanism is being modified. Emit R-011 at 3, omit R-002 (its score is 0, not 2).\n\n"
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
    # Phase 13 v1: pre-filter audit trail. The agent only judged relevance
    # for rows in ``ranked_risks``' candidate set; ``filtered_out_ids`` is
    # what the deterministic pre-filter excluded before the LLM saw the
    # register. A human reviewer can sanity-check whether any filtered row
    # should plausibly have been raised. ``prefilter_fallback_used`` is
    # True iff no pattern matched any file in the diff, in which case the
    # full register was sent to the agent.
    filtered_out_ids: list[str] = field(default_factory=list)
    prefilter_fallback_used: bool = False

    def to_json(self) -> dict:
        return {
            "summary": self.summary,
            "ranked_risks": self.ranked_risks,
            "exploratory_probes": self.exploratory_probes,
            "model": self.model,
            "filtered_out_ids": self.filtered_out_ids,
            "prefilter_fallback_used": self.prefilter_fallback_used,
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

    Phase 13 v1: a deterministic pre-filter narrows the register to rows whose
    layer/file mapping intersects the diff. The agent only judges relevance
    among the candidate set; the schema enum is also narrowed so the model
    physically cannot emit a filtered-out R-ID. Fallback: if no pattern
    matches any file in the diff, the full register is used (recall preserved
    in the unknown case).
    """
    candidates, filtered_out, fallback_used = candidate_risks(risks, diff)
    client = ollama.Client(host=host) if host else ollama
    schema = _schema([r.id for r in candidates])
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _user_message(candidates, diff)},
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
        filtered_out_ids=sorted(r.id for r in filtered_out),
        prefilter_fallback_used=fallback_used,
    )
