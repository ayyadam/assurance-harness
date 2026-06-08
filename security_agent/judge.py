"""LLM judgement over normalised findings — verdict + disposition + R-ID xref.

The heuristic spine (``findings.py``) already normalised and deduped; this is the
part that needs judgement. Per finding the model returns:

  - verdict       : true_positive | false_positive | expected_by_design
  - disposition   : remediate | allowlist | accept
  - candidate_risk_id : a register R-ID (closed vocabulary) or null
  - rationale     : grounded in the specific symptom, not generic talk

Mirrors ``triage_agent.cluster.categorise``: ``ollama`` structured output, a
closed-vocabulary R-ID enum the model can only pick from (never invent), and a
decision-procedure system prompt. The lesson from F-027 — anchor the call in an
explicit ordered procedure, not rules buried in prose — is applied here.
"""

from __future__ import annotations

import json
from typing import Any

import ollama

from risk_agent.register import Risk
from security_agent.findings import Finding

DEFAULT_MODEL = "qwen2.5:32b-instruct-q4_K_M"


_SYSTEM = (
    "You are a Digital Assurance Engineer triaging SECURITY SCANNER findings. Security scanners "
    "(bandit for SAST, pip-audit for SCA) are noisy: many findings are false positives or expected "
    "by design. Your job is to judge ONE finding and decide whether it is real, what should happen "
    "to it, and which risk-register row owns it.\n\n"
    "Return four fields. Decide them in this order:\n\n"
    "1) verdict — what IS this finding?\n"
    "   - false_positive: the scanner pattern-matched but it is not actually the vulnerability "
    "     claimed. Classic SAST examples: a string literal flagged as a 'hardcoded password' that is "
    "     really a NON-SECRET token name, a salt, an auth-scheme word like 'Bearer', or a header key. "
    "     The value is not a credential.\n"
    "   - expected_by_design: the finding is technically correct but the behaviour is intended and "
    "     acceptable in this context. Classic example: binding to 0.0.0.0 inside a container, where "
    "     listening on all interfaces is required and not a misconfiguration.\n"
    "   - true_positive: a genuine issue. A known CVE in a dependency (SCA) is almost always a "
    "     true_positive — the vulnerable code really is present; the only question is disposition.\n\n"
    "2) disposition — what should happen?\n"
    "   - accept: no action needed. Use for false_positive and expected_by_design.\n"
    "   - allowlist: a real issue accepted FOR NOW and tracked (e.g. a dependency CVE whose fix is a "
    "     deferred version bump). Records it against a register row instead of failing the build today.\n"
    "   - remediate: a real issue that should be fixed now.\n\n"
    "3) candidate_risk_id — which register row owns this?\n"
    "   - You are given the active risk register. Only return an R-ID that appears in it.\n"
    "   - Known-vulnerable dependencies (the SCA CVEs) are owned by the register's dependency-CVE "
    "     row. Match by mechanism, not vibe. If no row matches (most SAST false positives), return null.\n\n"
    "4) rationale — one or two sentences grounded in THIS finding's specifics (the rule id, the "
    "   flagged value, the file, the package/CVE). No generic security talk.\n\n"
    "Secret-scanner findings (tool=gitleaks, kind=secret): the matched VALUE is redacted — judge "
    "from the rule id and the file PATH. A real credential committed in application / config / "
    "deployment code is true_positive -> remediate (it must be rotated and removed). A match in a "
    "TEST FIXTURE, example, placeholder, sample, or documentation is false_positive -> accept. "
    "Paths under tests/, fixtures/, examples/, sample, or docs/ lean false_positive; paths under "
    "app/, config, deploy, or a committed .env lean true_positive.\n\n"
    "Judge the single finding you are given — not the codebase as a whole."
)


def _schema(risk_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["true_positive", "false_positive", "expected_by_design"],
            },
            "disposition": {"type": "string", "enum": ["remediate", "allowlist", "accept"]},
            "candidate_risk_id": {"type": ["string", "null"], "enum": [*risk_ids, None]},
            "rationale": {"type": "string"},
        },
        "required": ["verdict", "disposition", "candidate_risk_id", "rationale"],
    }


def _user_message(f: Finding, risks: list[Risk]) -> str:
    register = json.dumps([r.to_prompt_dict() for r in risks], indent=2)
    return (
        f"FINDING:\n"
        f"  tool:       {f.tool} ({f.kind})\n"
        f"  rule/id:    {f.rule_id}\n"
        f"  location:   {f.location}\n"
        f"  severity:   {f.severity}"
        f"{' / confidence ' + f.confidence if f.confidence else ''}\n"
        f"  title:      {f.title}\n"
        f"  detail:     {f.detail}\n\n"
        f"Risk register (JSON):\n{register}\n\n"
        "Judge this finding."
    )


def judge(f: Finding, risks: list[Risk], model: str = DEFAULT_MODEL, host: str | None = None) -> None:
    """Fill verdict, disposition, candidate_risk_id, rationale on the finding."""
    client = ollama.Client(host=host) if host else ollama
    schema = _schema([r.id for r in risks])
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _user_message(f, risks)},
        ],
        "format": schema,
        "options": {"temperature": 0},
    }
    try:
        response = client.chat(think=False, **kwargs)
    except ollama.ResponseError:
        response = client.chat(**kwargs)
    parsed = json.loads(response["message"]["content"])
    f.verdict = parsed["verdict"]
    f.disposition = parsed["disposition"]
    f.candidate_risk_id = parsed.get("candidate_risk_id") or None
    f.rationale = parsed["rationale"]
