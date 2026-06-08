"""Security agent — golden-set evaluation tier.

Treats the security agent like any model under test. The golden set
(``golden_set.yaml``) records the (verdict, disposition, R-ID) a reviewer would
assign per known finding. The evaluator reads the agent's cached
``reports/report.json`` and reports per-axis accuracy plus a combined
all-three-right score — deterministic, no LLM in the scoring path.

Mirrors ``triage_agent.eval`` / ``risk_agent.eval``: re-scoring after a
golden-set edit is free; ``--refresh`` re-runs the agent first.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_set.yaml"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"


@dataclass
class CaseScore:
    case_id: str
    signature: tuple[str, str, str]
    expected_verdict: str
    expected_disposition: str
    expected_risk_id: str | None
    actual_verdict: str | None
    actual_disposition: str | None
    actual_risk_id: str | None
    found: bool

    @property
    def verdict_match(self) -> bool:
        return self.found and self.expected_verdict == self.actual_verdict

    @property
    def disposition_match(self) -> bool:
        return self.found and self.expected_disposition == self.actual_disposition

    @property
    def risk_id_match(self) -> bool:
        return self.found and self.expected_risk_id == self.actual_risk_id

    @property
    def all_match(self) -> bool:
        return self.verdict_match and self.disposition_match and self.risk_id_match

    def to_json(self) -> dict:
        return {
            "case_id": self.case_id,
            "signature": list(self.signature),
            "expected": {
                "verdict": self.expected_verdict,
                "disposition": self.expected_disposition,
                "risk_id": self.expected_risk_id,
            },
            "actual": {
                "verdict": self.actual_verdict,
                "disposition": self.actual_disposition,
                "risk_id": self.actual_risk_id,
            },
            "found": self.found,
            "verdict_match": self.verdict_match,
            "disposition_match": self.disposition_match,
            "risk_id_match": self.risk_id_match,
            "all_match": self.all_match,
        }


def load_golden_set(path: Path = GOLDEN_SET_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["findings"]


def load_report(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def score_case(case: dict, report: list[dict]) -> CaseScore:
    sig = tuple(case["signature"])
    actual_v = actual_d = actual_r = None
    found = False
    for f in report:
        if tuple(f["signature"]) == sig:
            actual_v = f.get("verdict") or None
            actual_d = f.get("disposition") or None
            actual_r = f.get("candidate_risk_id")
            found = True
            break
    return CaseScore(
        case_id=case["id"],
        signature=sig,
        expected_verdict=case["expected_verdict"],
        expected_disposition=case["expected_disposition"],
        expected_risk_id=case.get("expected_risk_id"),
        actual_verdict=actual_v,
        actual_disposition=actual_d,
        actual_risk_id=actual_r,
        found=found,
    )


def aggregate(scores: list[CaseScore]) -> dict:
    n = len(scores) or 1
    v = sum(1 for s in scores if s.verdict_match)
    d = sum(1 for s in scores if s.disposition_match)
    r = sum(1 for s in scores if s.risk_id_match)
    a = sum(1 for s in scores if s.all_match)
    return {
        "cases": len(scores),
        "found": sum(1 for s in scores if s.found),
        "verdict_correct": v,
        "disposition_correct": d,
        "risk_id_correct": r,
        "all_correct": a,
        "verdict_accuracy": round(v / n, 3),
        "disposition_accuracy": round(d / n, 3),
        "risk_id_accuracy": round(r / n, 3),
        "combined_accuracy": round(a / n, 3),
    }


def render_eval_markdown(scores: list[CaseScore], totals: dict, today: date | None = None) -> str:
    today = today or date.today()
    n = totals["cases"]
    out: list[str] = []
    out.append("# security_agent — golden-set evaluation")
    out.append("")
    out.append(f"_Run: {today.isoformat()}_")
    out.append("")
    out.append(
        "Compares the agent's emitted (verdict, disposition, candidate_risk_id) per finding "
        "(cached in `reports/report.json`) against [`golden_set.yaml`](../golden_set.yaml). "
        "Scoring is deterministic — no LLM in the scoring path. Re-score after a golden-set edit "
        "is free; `--refresh` first re-runs the agent against the live scanners + Ollama."
    )
    out.append("")
    out.append("## Totals")
    out.append("")
    out.append("| Metric | Value |")
    out.append("|---|---|")
    out.append(f"| Cases | {n} |")
    out.append(f"| Findings matched in report | {totals['found']} / {n} |")
    out.append(f"| **Verdict accuracy** | **{totals['verdict_accuracy']:.3f}** ({totals['verdict_correct']}/{n}) |")
    out.append(
        f"| **Disposition accuracy** | **{totals['disposition_accuracy']:.3f}** ({totals['disposition_correct']}/{n}) |"
    )
    out.append(f"| **R-ID accuracy** | **{totals['risk_id_accuracy']:.3f}** ({totals['risk_id_correct']}/{n}) |")
    out.append(
        f"| **Combined (all three right)** | **{totals['combined_accuracy']:.3f}** ({totals['all_correct']}/{n}) |"
    )
    out.append("")
    out.append("## Per-case")
    out.append("")
    for s in scores:
        marker = "✓" if s.all_match else ("⚠" if s.found else "✗")
        out.append(f"### {marker} {s.case_id}")
        out.append("")
        out.append(f"**Signature:** `{s.signature[0]}` `{s.signature[1]}` — `{s.signature[2]}`")
        out.append("")
        if not s.found:
            out.append("_Finding signature not found in current report._")
            out.append("")
            continue
        vm = "✓" if s.verdict_match else "✗"
        dm = "✓" if s.disposition_match else "✗"
        rm = "✓" if s.risk_id_match else "✗"
        out.append(f"- {vm} verdict: expected `{s.expected_verdict}`, got `{s.actual_verdict}`")
        out.append(f"- {dm} disposition: expected `{s.expected_disposition}`, got `{s.actual_disposition}`")
        out.append(f"- {rm} R-ID: expected `{s.expected_risk_id or 'null'}`, got `{s.actual_risk_id or 'null'}`")
        out.append("")
    out.append("---")
    out.append("")
    out.append(
        "_Generated by `security_agent.eval`. Source of truth: "
        "[`golden_set.yaml`](../golden_set.yaml). Cached agent output: [`reports/report.json`](report.json)._"
    )
    out.append("")
    return "\n".join(out)


def refresh_run(sut: str, model: str, host: str | None) -> None:
    from security_agent.run import main as agent_main

    argv = ["--sut", sut, "--refresh", "--model", model]
    if host:
        argv += ["--host", host]
    rc = agent_main(argv)
    if rc != 0:
        raise RuntimeError(f"security_agent.run refresh failed with rc={rc}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="security_agent — golden-set evaluation")
    parser.add_argument("--golden-set", type=Path, default=GOLDEN_SET_PATH)
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--refresh", action="store_true", help="Re-run the agent before scoring (slow).")
    parser.add_argument("--sut", default="../golf-web-app", help="SUT path for --refresh.")
    parser.add_argument("--model", default="qwen2.5:32b-instruct-q4_K_M")
    parser.add_argument("--host", default=None)
    parser.add_argument("--no-write", action="store_true", help="Print but do not save eval-report.{md,json}")
    args = parser.parse_args(argv)

    if args.refresh:
        print("refreshing security report...", file=sys.stderr)
        refresh_run(args.sut, args.model, args.host)

    cases = load_golden_set(args.golden_set)
    report = load_report(args.reports_dir / "report.json")
    scores = [score_case(c, report) for c in cases]
    totals = aggregate(scores)
    md = render_eval_markdown(scores, totals)
    print(md)

    if not args.no_write:
        args.reports_dir.mkdir(parents=True, exist_ok=True)
        (args.reports_dir / "eval-report.md").write_text(md, encoding="utf-8")
        (args.reports_dir / "eval-report.json").write_text(
            json.dumps({"totals": totals, "cases": [s.to_json() for s in scores]}, indent=2),
            encoding="utf-8",
        )
        print(
            f"\nWrote: {args.reports_dir / 'eval-report.md'}\n       {args.reports_dir / 'eval-report.json'}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
