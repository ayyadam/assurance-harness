"""CLI for the risk-prioritisation agent.

Usage:
  uv run python -m risk_agent.run --pr 12 --repo ayyadam/golf-web-app
  uv run python -m risk_agent.run --diff path/to/file.diff
  uv run python -m risk_agent.run --pr 11 --repo ayyadam/golf-web-app --model qwen3:8b-fp16
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from risk_agent.agent import DEFAULT_MODEL, prioritise
from risk_agent.diff import DEFAULT_MAX_DIFF_LINES, DiffBundle, fetch_pr, load_file
from risk_agent.register import DEFAULT_REGISTER_PATH, parse_register
from risk_agent.render import render_markdown

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Risk-prioritisation agent (phase 9).")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--pr", type=int, help="GitHub PR number to fetch via gh")
    src.add_argument("--diff", type=Path, help="Path to a unified diff file")
    parser.add_argument("--repo", default="ayyadam/golf-web-app", help="GitHub repo for --pr (default: golf-web-app)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--host", default=None, help="Ollama host (default: env or localhost)")
    parser.add_argument(
        "--register",
        type=Path,
        default=DEFAULT_REGISTER_PATH,
        help="Path to risk-register.md (default: docs/risk-register.md)",
    )
    parser.add_argument(
        "--max-diff-lines",
        type=int,
        default=DEFAULT_MAX_DIFF_LINES,
        help=f"Truncate the diff body to this many lines (default: {DEFAULT_MAX_DIFF_LINES})",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Optional report filename stem (default: pr-NN or diff stem)",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print markdown to stdout but do not save under reports/",
    )
    args = parser.parse_args(argv)

    risks = parse_register(args.register)
    if not risks:
        print(f"error: no risks parsed from {args.register}", file=sys.stderr)
        return 2

    diff: DiffBundle
    if args.pr is not None:
        diff = fetch_pr(args.pr, args.repo, max_lines=args.max_diff_lines)
        label = args.label or f"pr-{args.pr}"
    else:
        diff = load_file(args.diff, max_lines=args.max_diff_lines)
        label = args.label or args.diff.stem

    print(
        f"agent: risks={len(risks)} files={len(diff.files)} "
        f"diff_lines={diff.total_lines} truncated={diff.truncated} model={args.model}",
        file=sys.stderr,
    )

    result = prioritise(risks, diff, model=args.model, host=args.host)
    md = render_markdown(result, diff)
    print(md)

    if not args.no_write:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        md_path = REPORTS_DIR / f"{label}-plan.md"
        json_path = REPORTS_DIR / f"{label}-plan.json"
        md_path.write_text(md, encoding="utf-8")
        json_path.write_text(json.dumps(result.to_json(), indent=2), encoding="utf-8")
        print(f"\nWrote: {md_path}\n       {json_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
