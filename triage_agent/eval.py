"""Triage agent — golden-set evaluation tier (v1 v2).

Treats the triage agent like any other model under test. The golden set
(``golden_set.yaml``) records the (category, R-ID) a reviewer would assign per
known cluster signature. The evaluator reads the agent's cached output
(``reports/report.json``) and reports per-axis accuracy plus a combined
both-right score — deterministic, no LLM in the scoring path.

Mirrors ``risk_agent.eval``: ``--refresh`` re-runs the agent before scoring;
the default reuses the cached run for free re-scoring after golden-set edits.
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
    expected_category: str
    expected_risk_id: str | None
    actual_category: str | None
    actual_risk_id: str | None
    found_in_report: bool

    @property
    def category_match(self) -> bool:
        return self.found_in_report and self.expected_category == self.actual_category

    @property
    def risk_id_match(self) -> bool:
        return self.found_in_report and self.expected_risk_id == self.actual_risk_id

    @property
    def both_match(self) -> bool:
        return self.category_match and self.risk_id_match

    def to_json(self) -> dict:
        return {
            "case_id": self.case_id,
            "signature": list(self.signature),
            "expected": {"category": self.expected_category, "risk_id": self.expected_risk_id},
            "actual": {"category": self.actual_category, "risk_id": self.actual_risk_id},
            "found_in_report": self.found_in_report,
            "category_match": self.category_match,
            "risk_id_match": self.risk_id_match,
            "both_match": self.both_match,
        }


def load_golden_set(path: Path = GOLDEN_SET_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["clusters"]


def load_report(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def score_case(case: dict, report_clusters: list[dict]) -> CaseScore:
    sig = case["signature"]
    sig_tuple = (sig["test_path"], sig["test_name"], sig["error_class"])
    expected_category = case["expected_category"]
    expected_risk_id = case.get("expected_risk_id")
    actual_category: str | None = None
    actual_risk_id: str | None = None
    found = False
    for c in report_clusters:
        if tuple(c["signature"]) == sig_tuple:
            actual_category = c.get("category") or None
            actual_risk_id = c.get("candidate_risk_id")
            found = True
            break
    return CaseScore(
        case_id=case["id"],
        signature=sig_tuple,
        expected_category=expected_category,
        expected_risk_id=expected_risk_id,
        actual_category=actual_category,
        actual_risk_id=actual_risk_id,
        found_in_report=found,
    )


def aggregate(scores: list[CaseScore]) -> dict:
    n = len(scores)
    found = sum(1 for s in scores if s.found_in_report)
    cat = sum(1 for s in scores if s.category_match)
    rid = sum(1 for s in scores if s.risk_id_match)
    both = sum(1 for s in scores if s.both_match)
    return {
        "cases": n,
        "found_in_report": found,
        "category_correct": cat,
        "risk_id_correct": rid,
        "both_correct": both,
        "category_accuracy": round(cat / n, 3) if n else 0.0,
        "risk_id_accuracy": round(rid / n, 3) if n else 0.0,
        "combined_accuracy": round(both / n, 3) if n else 0.0,
    }


def render_eval_markdown(scores: list[CaseScore], totals: dict, today: date | None = None) -> str:
    today = today or date.today()
    lines: list[str] = []
    lines.append("# triage_agent v1 v2 — golden-set evaluation")
    lines.append("")
    lines.append(f"_Run: {today.isoformat()}_")
    lines.append("")
    lines.append(
        "Compares the agent's emitted (category, candidate_risk_id) per cluster "
        "(cached in `reports/report.json`) against the expected values in "
        "[`golden_set.yaml`](../golden_set.yaml). Scoring is deterministic — no "
        "LLM in the scoring path. Re-score after a golden-set edit is free; "
        "`--refresh` first re-runs the agent against the live `gh` data."
    )
    lines.append("")

    lines.append("## Totals")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Cases | {totals['cases']} |")
    lines.append(f"| Clusters found in report | {totals['found_in_report']} / {totals['cases']} |")
    lines.append(
        f"| **Category accuracy** | **{totals['category_accuracy']:.3f}** "
        f"({totals['category_correct']}/{totals['cases']}) |"
    )
    lines.append(
        f"| **R-ID accuracy** | **{totals['risk_id_accuracy']:.3f}** ({totals['risk_id_correct']}/{totals['cases']}) |"
    )
    lines.append(
        f"| **Combined (both right)** | **{totals['combined_accuracy']:.3f}** "
        f"({totals['both_correct']}/{totals['cases']}) |"
    )
    lines.append("")

    lines.append("## Per-case")
    lines.append("")
    for s in scores:
        marker = "✓" if s.both_match else ("⚠" if s.found_in_report else "✗")
        lines.append(f"### {marker} {s.case_id}")
        lines.append("")
        sig_str = (
            f"`{s.signature[1]}` → `{s.signature[2]}`"
            if s.signature[0] == "<step>"
            else f"`{s.signature[0]}::{s.signature[1]}` → `{s.signature[2]}`"
        )
        lines.append(f"**Signature:** {sig_str}")
        lines.append("")
        if not s.found_in_report:
            lines.append("_Cluster signature not found in current report._")
            lines.append("")
            continue
        cat_mark = "✓" if s.category_match else "✗"
        rid_mark = "✓" if s.risk_id_match else "✗"
        lines.append(f"- {cat_mark} category: expected `{s.expected_category}`, got `{s.actual_category}`")
        lines.append(
            f"- {rid_mark} R-ID: expected `{s.expected_risk_id or 'null'}`, got `{s.actual_risk_id or 'null'}`"
        )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by `triage_agent.eval` (phase 10 v1 v2). Source of truth: "
        "[`golden_set.yaml`](../golden_set.yaml). Cached agent output: "
        "[`reports/report.json`](report.json)._"
    )
    lines.append("")
    return "\n".join(lines)


def refresh_run(repo: str, since_days: int, model: str, host: str | None) -> None:
    """Re-run the agent and overwrite `reports/report.json` before scoring."""
    from triage_agent.run import main as agent_main

    argv = ["--repo", repo, "--since-days", str(since_days), "--model", model]
    if host:
        argv += ["--host", host]
    rc = agent_main(argv)
    if rc != 0:
        raise RuntimeError(f"triage_agent.run refresh failed with rc={rc}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="triage_agent v1 v2 — golden-set evaluation")
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=GOLDEN_SET_PATH,
        help="Path to triage golden_set.yaml (default: triage_agent/golden_set.yaml)",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=REPORTS_DIR,
        help="Where report.json lives (default: triage_agent/reports)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-run the triage agent before scoring (slow — touches gh and Ollama).",
    )
    parser.add_argument(
        "--repo",
        default="ayyadam/assurance-harness",
        help="Repo for --refresh (default: ayyadam/assurance-harness)",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=30,
        help="--since-days for --refresh (default: 30)",
    )
    parser.add_argument("--model", default="qwen2.5:32b-instruct-q4_K_M")
    parser.add_argument("--host", default=None)
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print to stdout but do not save eval-report.{md,json}",
    )
    args = parser.parse_args(argv)

    if args.refresh:
        print("refreshing triage report...", file=sys.stderr)
        refresh_run(args.repo, args.since_days, args.model, args.host)

    cases = load_golden_set(args.golden_set)
    report = load_report(args.reports_dir / "report.json")
    scores = [score_case(c, report) for c in cases]
    totals = aggregate(scores)
    md = render_eval_markdown(scores, totals)
    print(md)

    if not args.no_write:
        args.reports_dir.mkdir(parents=True, exist_ok=True)
        md_path = args.reports_dir / "eval-report.md"
        json_path = args.reports_dir / "eval-report.json"
        md_path.write_text(md, encoding="utf-8")
        json_path.write_text(
            json.dumps({"totals": totals, "cases": [s.to_json() for s in scores]}, indent=2),
            encoding="utf-8",
        )
        print(f"\nWrote: {md_path}\n       {json_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
