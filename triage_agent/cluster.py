"""Cluster failures by signature and ask the LLM for category + risk cross-ref.

The heuristic clusters by ``(test_path, test_name, error_class)`` — failures
with the same shape almost always share the same cause. The LLM then assigns a
category (flake / defect / infra / env) and a candidate register R-ID per
cluster, with a rationale. The R-ID xref ties the triage output back to the
risk register, so a recurring flake immediately points at the responsible
mitigation row.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import ollama

from risk_agent.register import Risk
from triage_agent.fetcher import Run
from triage_agent.parser import Failure

DEFAULT_MODEL = "qwen2.5:32b-instruct-q4_K_M"


@dataclass
class ClusterMember:
    run: Run
    failure: Failure


@dataclass
class Cluster:
    signature: tuple[str, str, str]
    members: list[ClusterMember] = field(default_factory=list)
    category: str = ""  # "flake" | "defect" | "infra" | "env" | "unknown"
    rationale: str = ""
    candidate_risk_id: str | None = None  # R-NNN or None
    suggested_action: str = ""


# ── heuristic grouping ─────────────────────────────────────────────────────


def heuristic_cluster(runs_with_failures: list[tuple[Run, list[Failure]]]) -> list[Cluster]:
    """Group failures by ``(test_path, test_name, error_class)``. Single pass."""
    by_sig: dict[tuple[str, str, str], Cluster] = {}
    for run, failures in runs_with_failures:
        for f in failures:
            sig = f.signature
            cluster = by_sig.setdefault(sig, Cluster(signature=sig))
            cluster.members.append(ClusterMember(run=run, failure=f))

    # Sort: largest cluster first, then most recent member's run inside the cluster.
    def _key(c: Cluster) -> tuple[int, float]:
        return (-len(c.members), -max(m.run.created_at.timestamp() for m in c.members))

    return sorted(by_sig.values(), key=_key)


# ── LLM categorisation + R-ID xref ─────────────────────────────────────────


_SYSTEM = (
    "You triage CI failures for a Digital Assurance Engineer. You receive a CLUSTER of failures "
    "that share the same signature (test path, test name, error class) — they are almost certainly "
    "the same underlying issue. Your job is to assign a category, propose a candidate register R-ID "
    "(or 'none'), give a short rationale, and suggest a concrete next action for the on-call reviewer.\n\n"
    "Categories:\n"
    "  flake   — intermittent failure with no code change between pass and fail; timing or environment "
    "            races; passes on rerun.\n"
    "  defect  — a real bug in the SUT or harness; the failure is reproducible from the code at that "
    "            commit.\n"
    "  infra   — failure outside the code under test: CI runner cold-start, Docker network, action "
    "            tooling deprecation, image build failure.\n"
    "  env     — environment/config mismatch: missing secret, wrong service version, model not "
    "            available, dependency drift.\n\n"
    "Cross-reference rules:\n"
    "  - You are given the active risk register. Only return R-IDs that appear in the register.\n"
    "  - Match by mechanism, not vibe: a TimeoutError after a navigating click in functional tests is "
    "    R-018 because R-018 IS that risk. A k6 threshold breach is R-007. An a11y violation is R-008. "
    "    A contract mismatch is R-006. If no register row matches, return null.\n"
    "  - The rationale should ground in specific symptoms (the test name, the error class), not "
    "    generic talk.\n"
    "  - 'action' is the concrete next step a reviewer should take on THIS cluster — e.g. "
    "    'rerun the failed job', 'investigate the booking-confirm flow latency', 'run `uv run "
    "    ruff format` locally before next push'.\n"
)


def _schema(risk_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": ["flake", "defect", "infra", "env", "unknown"]},
            "candidate_risk_id": {"type": ["string", "null"], "enum": [*risk_ids, None]},
            "rationale": {"type": "string"},
            "suggested_action": {"type": "string"},
        },
        "required": ["category", "candidate_risk_id", "rationale", "suggested_action"],
    }


def _user_message(cluster: Cluster, risks: list[Risk]) -> str:
    register = json.dumps([r.to_prompt_dict() for r in risks], indent=2)
    members_summary = "\n".join(
        f"  - run #{m.run.number} ({m.run.event}, {m.run.created_at:%Y-%m-%d %H:%M}) "
        f"sha={m.run.sha[:7]} title={m.run.title!r}"
        for m in cluster.members
    )
    sig_path, sig_name, sig_err = cluster.signature
    f = cluster.members[0].failure
    return (
        f"CLUSTER signature:\n"
        f"  test path:  {sig_path}\n"
        f"  test name:  {sig_name}\n"
        f"  error class: {sig_err}\n"
        f"  kind: {f.kind}\n"
        f"  job: {f.job_name}\n"
        f"  representative error message:\n"
        f"    {f.error_message}\n\n"
        f"Cluster has {len(cluster.members)} failure(s):\n{members_summary}\n\n"
        f"Risk register (JSON):\n{register}\n\n"
        "Triage this cluster."
    )


def categorise(cluster: Cluster, risks: list[Risk], model: str = DEFAULT_MODEL, host: str | None = None) -> None:
    """Fill in category, rationale, candidate_risk_id, suggested_action on the cluster."""
    client = ollama.Client(host=host) if host else ollama
    schema = _schema([r.id for r in risks])
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _user_message(cluster, risks)},
        ],
        "format": schema,
        "options": {"temperature": 0},
    }
    try:
        response = client.chat(think=False, **kwargs)
    except ollama.ResponseError:
        response = client.chat(**kwargs)
    parsed = json.loads(response["message"]["content"])
    cluster.category = parsed["category"]
    cluster.candidate_risk_id = parsed.get("candidate_risk_id") or None
    cluster.rationale = parsed["rationale"]
    cluster.suggested_action = parsed["suggested_action"]
