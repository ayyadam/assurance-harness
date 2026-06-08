"""CLI for the security agent.

Local on-demand (needs a local Ollama runtime; raw scanners need the SUT checked
out as a sibling). Reads cached raw findings by default; ``--refresh`` re-runs the
scanners first.

Usage:
  uv run python -m security_agent.run
  uv run python -m security_agent.run --sut ../golf-web-app --refresh
  uv run python -m security_agent.run --no-llm     # normalise only, skip judgement
  uv run python -m security_agent.run --no-write   # print, don't save reports
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from risk_agent.register import parse_register
from security_agent.findings import DEFAULT_SUT, collect_findings
from security_agent.judge import DEFAULT_MODEL, judge
from security_agent.render import render_markdown, to_json

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Security agent — judge SAST + SCA findings (B1c).")
    parser.add_argument("--sut", default=str(DEFAULT_SUT), help="Path to the SUT checkout (golf-web-app).")
    parser.add_argument("--refresh", action="store_true", help="Re-run the scanners before judging (slow).")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--host", default=None, help="Ollama host (default: env or localhost)")
    parser.add_argument("--no-llm", action="store_true", help="Normalise only; skip LLM judgement.")
    parser.add_argument("--no-write", action="store_true", help="Print markdown but do not save reports.")
    args = parser.parse_args(argv)

    sut = Path(args.sut).resolve()
    print(f"collecting findings from {sut} (refresh={args.refresh})...", file=sys.stderr)
    findings = collect_findings(sut, refresh=args.refresh)
    print(f"normalised {len(findings)} finding(s)", file=sys.stderr)

    if not args.no_llm and findings:
        risks = parse_register()
        print(f"judging {len(findings)} finding(s) via {args.model}...", file=sys.stderr)
        for i, f in enumerate(findings, start=1):
            print(f"  {i}/{len(findings)}: {f.rule_id} {f.location}", file=sys.stderr)
            judge(f, risks, model=args.model, host=args.host)

    md = render_markdown(findings, sut=str(sut), model=None if args.no_llm else args.model)
    print(md)

    if not args.no_write:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "report.md").write_text(md, encoding="utf-8")
        (REPORTS_DIR / "report.json").write_text(to_json(findings), encoding="utf-8")
        print(f"\nWrote: {REPORTS_DIR / 'report.md'}\n       {REPORTS_DIR / 'report.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
