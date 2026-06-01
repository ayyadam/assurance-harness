"""CLI for the triage agent.

Usage:
  uv run python -m triage_agent.run --repo ayyadam/testing-system
  uv run python -m triage_agent.run --repo ayyadam/testing-system --since-days 7
  uv run python -m triage_agent.run --repo ayyadam/testing-system --no-llm    # skip categorisation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from risk_agent.register import parse_register
from triage_agent.cluster import DEFAULT_MODEL, categorise, heuristic_cluster
from triage_agent.fetcher import fetch_failed_log, list_failed_runs
from triage_agent.parser import parse_log
from triage_agent.render import render_markdown

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Triage agent — cluster failed CI runs.")
    parser.add_argument(
        "--repo",
        default="ayyadam/testing-system",
        help="GitHub repo to scan (default: ayyadam/testing-system)",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=30,
        help="Look back this many days for failed runs (default: 30)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum recent runs to scan (default: 100)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model for categorisation (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Ollama host (default: env or localhost)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip the LLM categorisation step. Heuristic clusters only.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print markdown to stdout but do not save report files.",
    )
    args = parser.parse_args(argv)

    print(f"scanning {args.repo} for failed runs in last {args.since_days} days...", file=sys.stderr)
    runs = list_failed_runs(args.repo, since_days=args.since_days, limit=args.limit)
    print(f"found {len(runs)} failed run(s)", file=sys.stderr)

    runs_with_failures: list = []
    for r in runs:
        log = fetch_failed_log(r.id, args.repo)
        failures = parse_log(log)
        runs_with_failures.append((r, failures))
        print(f"  run #{r.number}: parsed {len(failures)} failure(s)", file=sys.stderr)

    clusters = heuristic_cluster(runs_with_failures)
    print(f"clustered into {len(clusters)} group(s)", file=sys.stderr)

    if not args.no_llm and clusters:
        risks = parse_register()
        print(f"categorising {len(clusters)} cluster(s) via {args.model}...", file=sys.stderr)
        for i, c in enumerate(clusters, start=1):
            print(f"  cluster {i}/{len(clusters)}: {c.signature[1]} ({c.signature[2]})", file=sys.stderr)
            categorise(c, risks, model=args.model, host=args.host)

    md = render_markdown(
        clusters,
        repo=args.repo,
        since_days=args.since_days,
        total_runs_scanned=len(runs),
        model=None if args.no_llm else args.model,
    )
    print(md)

    if not args.no_write:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        md_path = REPORTS_DIR / "report.md"
        json_path = REPORTS_DIR / "report.json"
        md_path.write_text(md, encoding="utf-8")
        json_path.write_text(_to_json(clusters), encoding="utf-8")
        print(f"\nWrote: {md_path}\n       {json_path}", file=sys.stderr)
    return 0


def _to_json(clusters: list) -> str:
    out = []
    for c in clusters:
        out.append(
            {
                "signature": list(c.signature),
                "category": c.category,
                "candidate_risk_id": c.candidate_risk_id,
                "rationale": c.rationale,
                "suggested_action": c.suggested_action,
                "members": [
                    {
                        "run_id": m.run.id,
                        "run_number": m.run.number,
                        "run_url": m.run.url,
                        "event": m.run.event,
                        "branch": m.run.branch,
                        "sha": m.run.sha,
                        "title": m.run.title,
                        "created_at": m.run.created_at.isoformat(),
                        "test_path": m.failure.test_path,
                        "test_name": m.failure.test_name,
                        "test_params": m.failure.test_params,
                        "error_class": m.failure.error_class,
                        "error_message": m.failure.error_message,
                        "kind": m.failure.kind,
                        "job_name": m.failure.job_name,
                    }
                    for m in c.members
                ],
            }
        )
    return json.dumps(out, indent=2)


if __name__ == "__main__":
    sys.exit(main())
