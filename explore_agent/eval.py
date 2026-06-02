"""Explore agent — golden-set evaluation tier (v2 v1).

Mirrors ``risk_agent.eval`` and ``triage_agent.eval``. The golden set
(``golden_set.yaml``) records the category a reviewer would assign per
(endpoint, variant) probe combination. The evaluator reads the agent's
cached output (``reports/report.json``) and reports overall accuracy plus
a per-category confusion breakdown — deterministic, no LLM in the scoring
path.

Re-scoring after a golden-set edit is free; ``--refresh`` first re-runs the
agent against the live SUT.

What this eval measures
-----------------------
With no defects in the seeded surface, every case's expected category is
``expected``. The eval therefore quantifies one specific failure mode of
the agent: **over-flagging benign responses** (the documented v1 v1
limitation). Future judge-prompt tightening, prompt-engineering changes,
or a different judge model can all be scored against this baseline.

If a real defect is later introduced and the relevant golden-set case is
updated to a non-``expected`` category, the same scorer will then also
measure whether the agent **catches real defects** — without code change
to the eval.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_set.yaml"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"


@dataclass
class CaseScore:
    case_id: str
    endpoint: str  # "METHOD /path"
    variant: str  # happy | edge | abusive
    expected_category: str
    actual_category: str | None
    actual_status: int | None
    found_in_report: bool

    @property
    def category_match(self) -> bool:
        return self.found_in_report and self.expected_category == self.actual_category

    def to_json(self) -> dict:
        return {
            "case_id": self.case_id,
            "endpoint": self.endpoint,
            "variant": self.variant,
            "expected_category": self.expected_category,
            "actual_category": self.actual_category,
            "actual_status": self.actual_status,
            "found_in_report": self.found_in_report,
            "category_match": self.category_match,
        }


def load_golden_set(path: Path = GOLDEN_SET_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["cases"]


def load_report(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _signature(method: str, path: str) -> str:
    return f"{method} {path}"


def score_case(case: dict, report_findings: list[dict]) -> CaseScore:
    endpoint = case["endpoint"]
    variant = case["variant"]
    expected_category = case["expected_category"]
    actual_category: str | None = None
    actual_status: int | None = None
    found = False
    for f in report_findings:
        ep = f.get("endpoint", {})
        sig = _signature(ep.get("method", ""), ep.get("path", ""))
        v = f.get("variant", {}).get("label", "")
        if sig == endpoint and v == variant:
            actual_category = (f.get("finding") or {}).get("category")
            actual_status = (f.get("http") or {}).get("status")
            found = True
            break
    return CaseScore(
        case_id=case["id"],
        endpoint=endpoint,
        variant=variant,
        expected_category=expected_category,
        actual_category=actual_category,
        actual_status=actual_status,
        found_in_report=found,
    )


def aggregate(scores: list[CaseScore]) -> dict:
    n = len(scores)
    found = sum(1 for s in scores if s.found_in_report)
    correct = sum(1 for s in scores if s.category_match)
    # Confusion: for each expected_category, count how often each actual_category appeared.
    confusion: dict[str, Counter] = {}
    for s in scores:
        if not s.found_in_report:
            continue
        c = confusion.setdefault(s.expected_category, Counter())
        c[s.actual_category or "<missing>"] += 1
    return {
        "cases": n,
        "found_in_report": found,
        "category_correct": correct,
        "accuracy": round(correct / n, 3) if n else 0.0,
        "confusion": {k: dict(v) for k, v in confusion.items()},
    }


def render_eval_markdown(scores: list[CaseScore], totals: dict, today: date | None = None) -> str:
    today = today or date.today()
    lines: list[str] = []
    lines.append("# explore_agent v2 v1 — golden-set evaluation")
    lines.append("")
    lines.append(f"_Run: {today.isoformat()}_")
    lines.append("")
    lines.append(
        "Compares the agent's emitted category per (endpoint, variant) probe "
        "(cached in `reports/report.json`) against the expected values in "
        "[`golden_set.yaml`](../golden_set.yaml). Scoring is deterministic — no "
        "LLM in the scoring path. Re-score after a golden-set edit is free; "
        "`--refresh` first re-runs the agent against the live SUT."
    )
    lines.append("")

    lines.append("## Totals")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Cases | {totals['cases']} |")
    lines.append(f"| Probes found in report | {totals['found_in_report']} / {totals['cases']} |")
    lines.append(
        f"| **Overall accuracy** | **{totals['accuracy']:.3f}** ({totals['category_correct']}/{totals['cases']}) |"
    )
    lines.append("")

    lines.append("## Confusion")
    lines.append("")
    lines.append("Rows are expected categories; columns are what the agent emitted.")
    lines.append("")
    if not totals["confusion"]:
        lines.append("_No probes scored._")
    else:
        from explore_agent.judge import CATEGORIES

        cols = list(CATEGORIES)
        header = "| expected \\ actual | " + " | ".join(f"`{c}`" for c in cols) + " |"
        sep = "|---|" + "|".join("---" for _ in cols) + "|"
        lines.append(header)
        lines.append(sep)
        for expected in sorted(totals["confusion"].keys()):
            row_counts = totals["confusion"][expected]
            row = f"| `{expected}` | " + " | ".join(str(row_counts.get(c, 0)) for c in cols) + " |"
            lines.append(row)
    lines.append("")

    lines.append("## Per-case")
    lines.append("")
    for s in scores:
        marker = "✓" if s.category_match else ("⚠" if s.found_in_report else "✗")
        lines.append(f"### {marker} `{s.case_id}`")
        lines.append("")
        lines.append(f"**Probe:** `{s.endpoint}` — `{s.variant}`")
        lines.append("")
        if not s.found_in_report:
            lines.append("_Probe not found in current report._")
            lines.append("")
            continue
        cat_mark = "✓" if s.category_match else "✗"
        lines.append(
            f"- {cat_mark} category: expected `{s.expected_category}`, got `{s.actual_category}` "
            f"(http status {s.actual_status})"
        )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by `explore_agent.eval` (phase 12 v2 v1). Source of truth: "
        "[`golden_set.yaml`](../golden_set.yaml). Cached agent output: "
        "[`reports/report.json`](report.json)._"
    )
    lines.append("")
    return "\n".join(lines)


def refresh_run(base_url: str, model: str, host: str | None) -> None:
    """Re-run the API explore agent and overwrite `reports/report.json` before scoring."""
    from explore_agent.run import main as agent_main

    argv = ["--base-url", base_url, "--model", model]
    if host:
        argv += ["--host", host]
    rc = agent_main(argv)
    if rc != 0:
        raise RuntimeError(f"explore_agent.run refresh failed with rc={rc}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="explore_agent v2 v1 — golden-set evaluation")
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=GOLDEN_SET_PATH,
        help="Path to explore_agent/golden_set.yaml",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=REPORTS_DIR,
        help="Where report.json lives (default: explore_agent/reports)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-run the API explore agent before scoring (slow — touches the SUT and Ollama).",
    )
    parser.add_argument("--base-url", default="http://localhost:5000")
    parser.add_argument("--model", default="qwen2.5:32b-instruct-q4_K_M")
    parser.add_argument("--host", default=None)
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print to stdout but do not save eval-report.{md,json}",
    )
    args = parser.parse_args(argv)

    if args.refresh:
        print("refreshing explore_agent report...", file=sys.stderr)
        refresh_run(args.base_url, args.model, args.host)

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
